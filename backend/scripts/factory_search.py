"""Mac-only continuous research. Lives on factory/ledger; never merge.

24 candidates/night, two compute hours/night, Codex-plan batches plus bounded Claude fallback.
Reservations in the live ledger count before evaluation. Interrupted attempts
are consumed, never reopened (especially exams). Run --tick from launchd.
"""
from __future__ import annotations
import argparse
import hashlib
import shutil
import tempfile
import tomllib
import fcntl
import json
import os
import random
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

os.environ['ALPACA_DATA_FEED'] = 'sip'
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'backend/scripts'))
from dotenv import dotenv_values  # noqa: E402 — bootstrap SIP and the local environment first
for key, value in dotenv_values(ROOT / 'backend/.env').items():
    if value is not None:
        os.environ.setdefault(key, value)
from app.engine import factory_rules as rules  # noqa: E402 — bootstrap SIP and the local environment first
from app.engine.factory_data import ET, LEVEL_FEATURES  # noqa: E402 — bootstrap SIP and the local environment first
from app.engine.factory_brief import catalog, spec_changes, SPEC_FORMAT  # noqa: E402 — bootstrap SIP and the local environment first
from app.engine.factory_gates import evaluate, ledger_record, report, HOLDOUT_START  # noqa: E402 — bootstrap SIP and the local environment first
from strategy_factory import AlpacaCache, BarStore, LEDGER, DEFAULT_OUT, read_ledger, code_version, publish  # noqa: E402 — bootstrap SIP and the local environment first

OUT = DEFAULT_OUT / 'search'
NIGHT_CAP = 24
SECONDS_CAP = 7200
CLAUDE_USD_CAP = 2.0
CODEX_BATCH_CAP = 6
IDEA_SECONDS = 330
STORE = None




def append(record):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open('a') as handle:
        handle.write(json.dumps(record, allow_nan=False) + '\n')
        handle.flush()
        os.fsync(handle.fileno())


def latest(records):
    return {r['id']: r for r in records}


def night_key(now):
    return (now.date() if now.hour >= 22 else now.date() - timedelta(days=1)).isoformat()


def safe_digest(records):
    # Whitelist only discovery/confirmation data. Neither exam outcome nor
    # holdout numbers, notes or hand summaries can reach the idea model.
    return [dict(id=r['id'], spec=r.get('spec'), origin=r.get('search_origin'),
            screen={'passed': r.get('gates', {}).get('screen', {}).get('passed'),
                    'failed_checks': [text for text, passed in r.get('gates', {}).get('screen', {}).get('checks', []) if not passed]},
            periods={k: v for k, v in r.get('periods', {}).items()
            if k in ('discovery', 'confirm_a', 'confirm_b', 'confirm', 'confirm_x3')})
            for r in latest(records).values() if r.get('spec')]


def idea_prompt(records):
    return ('Propose up to four simple independent underlying setup specs from the catalog and ledger summaries. '
              'Only discovery and confirm evidence is provided. Never request or infer exam/holdout results. '
              'Use core tickers, default costs, no model, at most two filters, timeframe 5 for s1_research. '
              'Learn from the recorded failed screen checks, including earlier model-generated ideas. '
              'Separate insufficient samples from negative net R and insufficient evidence against random. '
              'Do not repeat a tried spec. State the failure addressed and the new testable hypothesis in notes; '
              'do not assume that an exit change will rescue an entry with no demonstrated edge. '
              'Every spec MUST explicitly set exits.max_sessions=1, including recovery_swing; this search is intraday only. '
              'Mix S1 orb/fade, other families, day/week and past-level context, and exits. Use notes, never note. Return {"specs":[...]}.\n' + SPEC_FORMAT + '\n'
              + json.dumps({'catalog': catalog(), 'ledger': safe_digest(records)}))


def claude_ideas(records, night, lock_fd=None):
    flag = OUT / f'{night}-claude-started'
    if flag.exists():
        queue = OUT / f'{night}-ideas.json'
        return json.loads(queue.read_text()) if queue.exists() else []
    flag.write_text('Reserved before launch: one plan call, max $2, max 300 seconds.\n')
    env = {k: v for k, v in os.environ.items() if not (
        k.startswith('CLAUDE_CODE_USE_') or k in ('ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_API_KEY',
        'ANTHROPIC_BASE_URL', 'ANTHROPIC_UNIX_SOCKET', 'CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR',
        'CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR'))}
    if not env.get('CLAUDE_CODE_OAUTH_TOKEN'):
        raise RuntimeError('Claude plan token missing; no API fallback')
    cli = os.environ.get('FACTORY_CLAUDE', str(Path.home() / '.local/node/bin/claude'))
    status = subprocess.run([cli, 'auth', 'status', '--json'], env=env, capture_output=True, text=True,
                            check=True, timeout=30)
    auth = json.loads(status.stdout)
    if auth.get('authMethod') != 'oauth_token' or auth.get('apiProvider', 'firstParty') != 'firstParty' or auth.get('apiKeySource'):
        raise RuntimeError('Claude plan preflight refused sign-in')
    schema = {'type': 'object', 'properties': {'specs': {'type': 'array', 'maxItems': 4,
              'items': {'type': 'object'}}}, 'required': ['specs']}
    prompt = idea_prompt(records)
    (OUT / f'{night}-brief.json').write_text(prompt)
    command = [cli, '-p', '--restricted', '--strict-mcp-config', '--tools', '', '--model', 'opus',
               '--effort', 'high', '--system-prompt', 'Follow the supplied factory research brief only.',
               '--json-schema', json.dumps(schema), '--permission-mode', 'dontAsk', '--permission-prompts', 'none',
               '--max-budget-usd', str(CLAUDE_USD_CAP), '--no-session-persistence', '--output-format', 'json']
    answer = subprocess.run(command, input=prompt, env=env, capture_output=True, text=True, check=True, timeout=300,
                            preexec_fn=lambda: signal.alarm(300),
                            pass_fds=(() if lock_fd is None else (lock_fd,)))
    raw = json.loads(answer.stdout)
    if raw.get('is_error'):
        raise RuntimeError('Claude returned an error')
    structured = raw.get('structured_output')
    if structured is None:
        structured = json.loads(raw['result'])
    ideas = structured['specs']
    (OUT / f'{night}-ideas.json').write_text(json.dumps(ideas))
    return ideas


def fresh_ideas(ideas, records):
    seen = set(latest(records))
    fresh = []
    for raw in ideas:
        try:
            spec = validate(raw)
        except (ValueError, TypeError):
            continue
        ident = rules.spec_id(spec)
        if ident not in seen:
            fresh.append(raw)
            seen.add(ident)
    return fresh


def codex_command(cli, schema, answer, model=None):
    command = [cli, 'exec', '--ignore-user-config', '--ephemeral', '--skip-git-repo-check',
               '--sandbox', 'read-only', '--json', '--color', 'never',
               '--output-schema', str(schema), '--output-last-message', str(answer)]
    settings = {'forced_login_method': 'chatgpt', 'model_provider': 'openai',
                'web_search': 'disabled', 'project_doc_max_bytes': 0,
                'memories.use_memories': False, 'memories.generate_memories': False,
                'mcp_servers': {}}
    for name, value in settings.items():
        command += ['-c', name + '=' + json.dumps(value)]
    for feature in ('shell_tool', 'plugins', 'hooks', 'multi_agent', 'memories'):
        command += ['--disable', feature]
    command += ['-c', 'features.skip_host_skill_discovery=true']
    if model:
        command += ['--model', model]
    return command + ['-']


def codex_ideas(records, night, reserve_seconds, lock_fd=None):
    queue = OUT / f'{night}-codex-ideas.json'
    ideas = json.loads(queue.read_text()) if queue.exists() else []
    available = fresh_ideas(ideas, records)
    if available:
        return available
    started = list(OUT.glob(f'{night}-codex-batch-*.started.json'))
    if len(started) >= CODEX_BATCH_CAP:
        return []
    # Reserve both time and batch identity before launching any model process.
    reserve_seconds(IDEA_SECONDS)
    number = len(started) + 1
    base = OUT / f'{night}-codex-batch-{number:02}'
    flag = base.with_suffix('.started.json')
    flag.write_text(json.dumps({'started_at': datetime.now(ET).isoformat(),
                                'reserved_seconds': IDEA_SECONDS, 'origin': 'codex-plan'}))
    env = {k: v for k, v in os.environ.items() if k in (
        'HOME', 'USER', 'LOGNAME', 'PATH', 'TMPDIR', 'LANG', 'LC_ALL', 'CODEX_HOME',
        'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY', 'SSL_CERT_FILE', 'SSL_CERT_DIR')}
    cli = shutil.which('codex') or '/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'
    config = Path(env.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'config.toml'
    model = tomllib.loads(config.read_text()).get('model') if config.exists() else None
    receipt = {'origin': 'codex-plan', 'model': model, 'state': 'started', 'feedback_mode': 'catalog-only'}
    began = time.monotonic()
    try:
        status = subprocess.run([cli, 'login', 'status'], env=env, capture_output=True,
                                text=True, check=True, timeout=30)
        if 'Logged in using ChatGPT' not in status.stdout + status.stderr:
            raise RuntimeError('Codex must use ChatGPT login; no API fallback')
        prompt = ('Use only this supplied research brief; do not use tools, files, memories or external data. '
                  'Encode the proposed specs array as JSON text in the required specs_json string field.\n'
                  + idea_prompt([]))
        brief = base.with_suffix('.brief.txt')
        brief.write_text(prompt)
        receipt['brief_sha256'] = hashlib.sha256(prompt.encode()).hexdigest()
        schema = base.with_suffix('.schema.json')
        schema.write_text(json.dumps({'type': 'object', 'properties': {'specs_json': {'type': 'string'}},
                                     'required': ['specs_json'], 'additionalProperties': False}))
        answer = base.with_suffix('.answer.json')
        with tempfile.TemporaryDirectory(prefix='factory-codex-') as empty:
            process = subprocess.Popen(codex_command(cli, schema, answer, model), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=empty, env=env,
                start_new_session=True, preexec_fn=lambda: signal.alarm(300),
                pass_fds=(() if lock_fd is None else (lock_fd,)))
            try:
                stdout, stderr = process.communicate(prompt, timeout=300)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.communicate(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate(timeout=15)
                raise
        base.with_suffix('.events.jsonl').write_text(stdout)
        base.with_suffix('.stderr.txt').write_text(stderr)
        if process.returncode:
            raise RuntimeError('Codex generation failed; see private generation receipt')
        events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        items = [e['item'].get('type') for e in events if isinstance(e.get('item'), dict)]
        if set(items) - {'reasoning', 'agent_message'}:
            raise RuntimeError('Unexpected Codex tool use; proposals refused')
        receipt['usage'] = [e.get('usage') for e in events if e.get('type') == 'turn.completed']
        raw = json.loads(json.loads(answer.read_text())['specs_json'])
        if not isinstance(raw, list) or not 1 <= len(raw) <= 4 or not all(isinstance(x, dict) for x in raw):
            raise ValueError('Codex must return one to four proposal objects')
        accepted = fresh_ideas(raw, records)
        receipt.update(state='completed', proposed=len(raw), accepted=len(accepted))
        temporary = queue.with_suffix('.tmp')
        temporary.write_text(json.dumps(ideas + accepted))
        temporary.replace(queue)
        print(f'Codex proposal batch {number}: {len(accepted)}/{len(raw)} valid new ideas', flush=True)
        return accepted
    except BaseException as exc:
        receipt.update(state='failed', error=type(exc).__name__)
        raise
    finally:
        receipt['elapsed_seconds'] = round(time.monotonic() - began, 3)
        base.with_suffix('.receipt.json').write_text(json.dumps(receipt, indent=2))
        for file in OUT.glob(base.name + '.*'):
            file.chmod(0o600)


def sample(rng):
    family = rng.choice(list(rules.FAMILIES))
    spec = {'name': 'Continuous setup search', 'family': family,
            'exits': {'target_r': rng.choice([1.5, 2.0, 2.5, 3.0]), 'max_sessions': 1,
                      'max_minutes': rng.choice([20, 30, 60, 120])}}
    if family == 's1_research':
        spec['params'] = {'setup': rng.choice(['orb', 'fade'])}
    elif family == 'opening_range_breakout':
        spec['params'] = {'range_minutes': rng.choice([5, 15, 30]), 'stop_at': rng.choice(['range', 'mid'])}
    candidates = ['gap', 'day_move', 'trend', 'trend_slope', 'spy_trend', 'spy_day', 'spy_vol',
                  'vol_ratio', 'rel_strength', *LEVEL_FEATURES]
    spec['filters'] = []
    for feature in rng.sample(candidates, rng.choice([1, 2])):
        threshold = rng.choice([-0.5, 0, 0.5, 1.0])
        if feature in ('vol_ratio', 'spy_vol'):
            threshold = rng.choice([0.75, 1.0, 1.5, 2.0])
        spec['filters'].append({'feature': feature, rng.choice(['min', 'max']): threshold})
    return spec


def validate(raw):
    raw = dict(raw)
    if 'note' in raw and 'notes' not in raw:
        raw['notes'] = raw.pop('note')
    # Claude sees canonical ledger specs (low/high), while CLI specs use
    # min/max. Accept an unambiguous spelling translation without altering
    # a bound, cost, exit, timeframe or gate.
    if isinstance(raw.get('filters'), (list, tuple)):
        filters = []
        for item in raw['filters']:
            item = dict(item)
            for stored, public in (('low', 'min'), ('high', 'max')):
                if stored in item:
                    value = item.pop(stored)
                    if public in item and item[public] != value:
                        raise ValueError(f'conflicting filter bounds: {stored}/{public}')
                    if value is not None:
                        item[public] = value
            filters.append(item)
        raw['filters'] = filters
    spec = rules.parse_spec(raw)
    if spec.model is not None or spec.tickers != rules.CORE_UNIVERSE or spec.costs != rules.Costs() or len(spec.filters) > 2:
        raise ValueError('Search may not alter universe/costs, train models, or use more than two filters')
    if spec.exits.max_sessions != 1:
        raise ValueError('Search is intraday only')
    return spec


def worker(path):
    global STORE
    job = json.loads(Path(path).read_text())
    # This deadline survives termination of the supervising launchd tick.
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.alarm(job.get('timeout_seconds', 900))
    spec = rules.from_canonical(job['spec'])
    STORE = BarStore(AlpacaCache(), DEFAULT_OUT, lambda s: print(s, flush=True))
    # Existing April-2026 holdout is larger than four weeks; never shrink it.
    if HOLDOUT_START > datetime.now(ET).date() - timedelta(weeks=4):
        raise RuntimeError('Configured holdout does not protect the latest four weeks')
    ev = evaluate(spec, STORE.load, job['prior_candidates'], exam=True, progress=lambda s: print(s, flush=True))
    record = ledger_record(ev, datetime.now(ET), code_version(), STORE.last_day(rules.MARKET))
    record.update(source='continuous-search', search_night=job['search_night'], attempt_state='completed', search_origin=job['search_origin'])
    destination = Path(path).with_suffix('.result.json')
    temporary = destination.with_suffix('.tmp')
    temporary.write_text(json.dumps(record))
    temporary.replace(destination)
    Path(path).with_suffix('.report.txt').write_text(report(ev))


def summary(records, night):
    results = [r for r in latest(records).values() if r.get('search_night') == night]
    confirm = [r for r in results if r.get('periods', {}).get('confirm')]
    confirm.sort(key=lambda r: r['periods']['confirm'].get('mean_r') or -1e9, reverse=True)
    top = [dict(id=r['id'], confirm=r['periods']['confirm'], verdict=r['verdict']) for r in confirm[:3]]
    return dict(night=night, tried=len(results), completed=sum(r.get('attempt_state') == 'completed' for r in results),
                exam_passes=[r['id'] for r in results if r.get('verdict') == 'passed'], best_confirm=top)


def notify(records, night):
    flag = OUT / f'{night}-notified'
    if flag.exists():
        return
    data = summary(records, night)
    report_file = ROOT / 'research/reports' / f'{night}-continuous.json'
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(data, indent=2) + '\n')
    settings = dict(os.environ)
    alerts = Path(os.environ.get('FACTORY_ALERTS_ENV', str(Path.home() / '.config/tradejournal/alerts.env')))
    if alerts.exists():
        settings.update({k: v for k, v in dotenv_values(alerts).items() if v})
    url = settings.get('NTFY_URL') or settings.get('FACTORY_NTFY_URL')
    if not url:
        raise RuntimeError('ntfy URL unavailable in alerts.env or factory environment')
    message = f"{night}: {data['tried']} tried, {data['completed']} completed. Exam passes: {len(data['exam_passes'])}."
    for row in data['best_confirm']:
        message += f" Confirm {row['id']}: {json.dumps(row['confirm'])}."
    publish(url, settings.get('NTFY_TOKEN') or settings.get('FACTORY_NTFY_TOKEN'), 'S1 setup search daily',
            message[:3500], None, 4 if data['exam_passes'] else 3, ['chart_with_upwards_trend'])
    flag.write_text(datetime.now(ET).isoformat())


def proposal(record):
    if record.get('verdict') == 'passed':
        path = ROOT / 'research/reports' / f"s1-v3-proposal-{record['id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'status': 'Isaac approval and forward paper required; no activation',
                                        'evidence': record}, indent=2))
        temporary.replace(path)


def reconcile_proposals(records):
    # Replay even when completion was appended before a supervisor interruption.
    for record in latest(records).values():
        if record.get('search_night'):
            proposal(record)


def persist_research():
    paths = [LEDGER, *ROOT.glob('research/specs/search-*.json'),
             *ROOT.glob('research/reports/*-continuous.json'),
             *ROOT.glob('research/reports/s1-v3-proposal-*.json')]
    subprocess.run(['git', 'add', '--', *map(str, paths)], cwd=ROOT, check=True)
    changed = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=ROOT).returncode
    if changed:
        subprocess.run(['git', 'commit', '-m', 'Continuous setup search: retain trials and daily evidence'], cwd=ROOT, check=True)
    subprocess.run(['git', 'push', 'origin', 'factory/ledger'], cwd=ROOT, check=True, timeout=60)


def tick(force=False):
    if ROOT != Path('/Users/user/TradeJournal-factory'):
        raise RuntimeError('Search runs only in the Mac factory checkout')
    if subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip() != 'factory/ledger':
        raise RuntimeError('Live search requires factory/ledger')
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / 'writer.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        # Share the weekly wrapper's exclusion. Stale locks are only reclaimed
        # when owned by this search and its PID is provably absent.
        lock = DEFAULT_OUT / 'week.lock'
        if lock.exists():
            owner = lock / 'search-pid'
            if not owner.exists():
                return
            try:
                os.kill(int(owner.read_text()), 0)
                return
            except ProcessLookupError:
                owner.unlink()
                lock.rmdir()
        lock.mkdir()
        (lock / 'search-pid').write_text(str(os.getpid()))
        try:
            now = datetime.now(ET)
            records = read_ledger(LEDGER)
            # Recover atomic result files written before parent interruption;
            # never rerun reserved IDs or reopen any exam.
            for job in OUT.glob('*.job.json'):
                reservation = json.loads(job.read_text())
                found = latest(records).get(reservation['id'])
                if found and found.get('attempt_state') == 'reserved':
                    result = job.with_suffix('.result.json')
                    done = json.loads(result.read_text()) if result.exists() else {**found, 'attempt_state': 'interrupted', 'verdict': 'interrupted'}
                    append(done)
                    records.append(done)
                    proposal(done)
            reconcile_proposals(records)
            for night in sorted({r['search_night'] for r in records if r.get('search_night')}):
                if night != night_key(now) or (6 <= now.hour < 22):
                    notify(records, night)
            if not force and 6 <= now.hour < 22:
                return
            night = night_key(now)
            reservations = [r for r in records if r.get('search_night') == night and r.get('attempt_state') == 'reserved']
            if len(reservations) >= NIGHT_CAP:
                return
            # Reserve worst-case seconds before each external process; interrupted
            # processes cannot reset the nightly budget.
            budget = OUT / f'{night}-seconds.json'
            used = json.loads(budget.read_text()) if budget.exists() else 0
            if used >= SECONDS_CAP:
                return
            def reserve_seconds(amount):
                nonlocal used
                if used + amount > SECONDS_CAP:
                    raise RuntimeError('Not enough remaining time for a model batch')
                used += amount
                tmp = budget.with_suffix('.tmp')
                tmp.write_text(json.dumps(used))
                tmp.replace(budget)
            ideas = []
            idea_origin = 'codex-plan'
            try:
                ideas = codex_ideas(records, night, reserve_seconds, handle.fileno())
            except Exception as exc:
                print('Codex proposal unavailable (bounded fallback continues):', type(exc).__name__, flush=True)
            if not ideas:
                idea_origin = 'claude-plan'
                try:
                    if not (OUT / f'{night}-claude-started').exists():
                        reserve_seconds(IDEA_SECONDS)
                    ideas = claude_ideas(records, night, handle.fileno())
                except Exception as exc:
                    print('Claude proposal unavailable (random search continues):', type(exc).__name__, flush=True)
                    (OUT / f'{night}-claude-failure.txt').write_text(type(exc).__name__ + '\n')
            seen = set(latest(records))
            rng = random.Random(os.urandom(16))
            chosen = None
            for raw in ideas + [sample(rng) for _ in range(100)]:
                try:
                    spec = validate(raw)
                except (ValueError, TypeError) as exc:
                    if raw in ideas:
                        refusal = {'at': datetime.now(ET).isoformat(), 'origin': idea_origin,
                                   'reason': str(exc), 'spec': raw}
                        with (OUT / f'{night}-proposal-rejections.jsonl').open('a') as log:
                            log.write(json.dumps(refusal) + '\n')
                        print(f'{idea_origin} proposal rejected: {exc}', flush=True)
                    continue
                if rules.spec_id(spec) not in seen:
                    chosen = spec
                    origin = idea_origin if raw in ideas else 'random'
                    break
            if chosen is None:
                raise RuntimeError('No distinct valid proposal')
            timeout = min(900, SECONDS_CAP - used)
            if timeout < 60:
                return
            reserve_seconds(timeout)
            ident = rules.spec_id(chosen)
            reservation = dict(id=ident, name=chosen.name, source='continuous-search', spec=rules.canonical(chosen),
                recorded=now.isoformat(), code=code_version(), verdict='reserved', attempt_state='reserved',
                reached_confirmation=False, search_night=night, prior_candidates=len(seen), search_origin=origin, timeout_seconds=timeout)
            job = OUT / f'{ident}.job.json'
            job.write_text(json.dumps(reservation))
            spec_path = ROOT / 'research/specs' / f'search-{ident}.json'
            spec_path.write_text(json.dumps({'family': chosen.family, 'name': chosen.name, **spec_changes(rules.canonical(chosen))}, indent=2) + '\n')
            append(reservation)
            print(f'{now.isoformat()} reserved {ident}; K={len(seen)+1}; {origin}', flush=True)
            process = subprocess.Popen([sys.executable, __file__, '--worker', str(job)], start_new_session=True, pass_fds=(handle.fileno(),))
            started = time.monotonic()
            try:
                result_code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=15)
                result_code = -1
            used -= max(0, timeout - int(time.monotonic() - started + 1))
            budget.write_text(json.dumps(used))
            result_path = job.with_suffix('.result.json')
            if result_code == 0 and result_path.exists():
                result = json.loads(result_path.read_text())
            else:
                result = {**reservation, 'attempt_state': 'failed', 'verdict': 'evaluation_error'}
            append(result)
            print(f'{datetime.now(ET).isoformat()} {ident}: {result["verdict"]}', flush=True)
            proposal(result)
        finally:
            try:
                persist_research()
            finally:
                (lock / 'search-pid').unlink(missing_ok=True)
                lock.rmdir()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tick', action='store_true')
    parser.add_argument('--force', action='store_true', help='one acceptance run outside nightly hours')
    parser.add_argument('--worker')
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
    elif args.tick:
        tick(args.force)
