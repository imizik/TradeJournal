"""Offline opportunity-feed pilot; factory/ledger only. No live services or model calls.

Reuses already tried IDs, discovery data only, and separately frozen Jo choices.
Run build under the existing search writer lock/time budget. Public cards omit
all outcomes. Private outcome files are operator-only workflow separation, not
an authenticated Jo endpoint; do not give Jo filesystem access to this folder.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import random
import secrets
import signal
import sys
import time
from types import SimpleNamespace

os.environ['ALPACA_DATA_FEED'] = 'sip'
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'backend'))
sys.path.insert(0, str(ROOT/'backend/scripts'))
def _load_factory():
    # Imports follow SIP/path bootstrap without suppressing the import-order check.
    import factory_search as search
    from app.engine.factory_gates import PERIODS
    from app.engine.factory_data import FeatureContext
    return search, PERIODS, FeatureContext


search, PERIODS, FeatureContext = _load_factory()

VERSION = 'opportunity-pilot-v1'
IDS = ('s1-0b2c5f54ba', 's1-455b2eabc7', 'op-7f71884194',
       'vw-977e9301a5', 'fa-51ce18820a', 're-e3945c3bc9')
# Fixed prospectively for this historical pilot, before loading/scoring its trades.
DAYS = tuple(date(2024, 2, 5) + timedelta(days=i) for i in range(5))
SEED = 10415
MAX_PER_DAY = 18
MAX_PER_TICKER_DAY = 3
MIN_TARGET_R = 1.25
MAX_COST_R = 0.25
BATCH = ROOT/'backend/data/factory/opportunities/pilot-20261015-v2'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(canonical(value)+'\n')
    tmp.replace(path)


def packet(spec, trade, series):
    i = trade.signal_index
    cutoff = series.time[i] + timedelta(minutes=series.timeframe)
    reference = series.close[i]
    risk = trade.side * (reference-trade.stop)
    target_r = spec.exits.target_r
    if risk <= 0 or target_r is None or target_r < MIN_TARGET_R:
        return None
    cost_r = 2 * spec.costs.slip(reference) / risk
    if cost_r > MAX_COST_R:
        return None
    # Only pre-decision features; neither actual next-open fill nor actual
    # target computed from that future fill enters the public plan.
    rows = [dict(start=t.isoformat(), end=(t+timedelta(minutes=series.timeframe)).isoformat(),
                 open=series.open[j], high=series.high[j], low=series.low[j],
                 close=series.close[j], volume=series.volume[j])
            for j, t in enumerate(series.time[:i+1])
            if (t+timedelta(minutes=series.timeframe)) <= cutoff][-60:]
    factor = math.prod(split.ratio for split in series.splits if split.day > cutoff.astimezone(search.ET).date())
    for row in rows:
        for field in ('open','high','low','close'):
            row[field] *= factor
        row['volume'] /= factor
    identity = dict(spec_id=search.rules.spec_id(spec), ticker=trade.ticker,
                    signal_time=trade.signal_time.isoformat(), side=trade.side)
    card = dict(id=digest(identity)[:20], schema=VERSION, candidate=identity,
                family=spec.family, setup=dict(spec.params).get('setup', spec.family), timeframe_minutes=series.timeframe,
                simulated_as_of=cutoff.isoformat(), entry_reference=reference*factor,
                stop=trade.stop*factor, target_reference=(reference+trade.side*target_r*risk)*factor,
                target_r=target_r, max_minutes=spec.exits.max_minutes,
                features=clean(trade.features), estimated_round_trip_cost_r=cost_r,
                option_eligibility={'available': False, 'reason': 'No historical option quotes, spreads or contract evidence'},
                candles=rows, source='cached Alpaca SIP; retrospective data, may contain corrections',
                labels=['offline-research', 'underlying-only', 'independence-unverified',
                        'options-liquidity-unverified', 'split-adjusted-to-decision-basis'])
    return card


def balanced(cards):
    # Fixed quotas and hash ordering; no return, win/loss, or future path enters.
    grouped = defaultdict(lambda: defaultdict(list))
    for card in cards:
        day = card['simulated_as_of'][:10]
        grouped[day][card['candidate']['spec_id']].append(card)
    chosen = []
    for day, families in sorted(grouped.items()):
        queues = {key: sorted(items, key=lambda c: digest([SEED, c['id']]))
                  for key, items in families.items()}
        counts = Counter()
        used = set()
        day_count = 0
        while any(queues.values()) and day_count < MAX_PER_DAY:
            for key in sorted(queues):
                if not queues[key] or day_count >= MAX_PER_DAY:
                    continue
                card = queues[key].pop(0)
                ticker = card['candidate']['ticker']
                shared = (ticker, card['candidate']['signal_time'], card['candidate']['side'])
                if counts[ticker] >= MAX_PER_TICKER_DAY or shared in used:
                    continue
                counts[ticker] += 1
                used.add(shared)
                day_count += 1
                chosen.append(card)
    return sorted(chosen, key=lambda c: (c['simulated_as_of'], c['candidate']['ticker'], c['id']))


def build(batch=BATCH):
    if batch.exists():
        raise ValueError('Frozen pilot exists; refuse replacement')
    records=search.latest(search.read_ledger(search.LEDGER))
    specs=[]
    for identifier in IDS:
        row=records[identifier]
        if row.get('attempt_state') != 'completed':
            raise ValueError('Only completed, previously counted specs may enter this pilot')
        spec=search.rules.from_canonical(row['spec'])
        if search.rules.spec_id(spec)!=identifier or spec.exits.max_sessions!=1 or spec.exits.moves_stop:
            raise ValueError('Pilot needs unchanged intraday specs with fixed stops')
        specs.append(spec)
    if DAYS[-1] > PERIODS['discovery'][1]:
        raise ValueError('Pilot must remain inside discovery')
    store=search.BarStore(search.AlpacaCache(),search.DEFAULT_OUT,lambda x:print(x,flush=True))
    def load(ticker, timeframe, through):
        if through is None or through>DAYS[-1]:
            through=DAYS[-1]
        return store.load(ticker,timeframe,through)
    cards=[]
    raw_counts=Counter()
    rejected=Counter()
    series_cache={}
    signal_map={}
    spec_map={}
    for spec in specs:
        ident=search.rules.spec_id(spec)
        spec_map[ident]=spec
        market=load(search.rules.MARKET,spec.timeframe,DAYS[-1])
        for ticker in spec.tickers:
            key=(ticker,spec.timeframe)
            if key not in series_cache:
                series_cache[key]=load(ticker,spec.timeframe,DAYS[-1])
            series=series_cache[key]
            if series is None:
                continue
            context=FeatureContext(series,market)
            family=spec.rules().start(series)
            def accept(sig):
                if spec.window and not spec.window[0]<=series.close_minute(sig.index)<=spec.window[1]:
                    return False
                return all(rule.passes(context.at(sig.index,sig.side,sig.stop)) for rule in spec.filters)
            for i in range(len(series)):
                # Independent opportunities, no future-fill or outcome-dependent
                # position suppression. Fixed public quotas bound the pilot feed.
                sig=family.on_bar(i,search.rules.Context(flat=True,halted=False,accept=accept))
                if sig is None or series.days[series.session[i]] not in DAYS:
                    continue
                day=str(series.days[series.session[i]])
                raw_counts[day]+=1
                provisional=SimpleNamespace(signal_index=i,signal_time=series.time[i],ticker=ticker,
                    side=sig.side,stop=sig.stop,features=context.at(i,sig.side,sig.stop))
                card=packet(spec,provisional,series)
                if card is None:
                    rejected[day]+=1
                    continue
                cards.append(card)
                signal_map[card['id']]=(spec,series,sig)
    chosen=balanced(cards)
    # Continuations are evaluated only AFTER the outcome-blind admission/sample.
    outcomes={}
    for card in chosen:
        spec,series,sig=signal_map[card['id']]
        trades=search.rules.run_each(series,[sig],spec.exits,spec.costs)
        trade=trades[0] if trades else None
        outcomes[card['id']]={'resolved':bool(trade and trade.closed),
                             'r':trade.r if trade and trade.closed else None}
    public={'schema':VERSION,'frozen_at':datetime.now(search.ET).isoformat(),
            'sessions':[str(d) for d in DAYS], 'seed':SEED, 'spec_ids':list(IDS),
            'quality_policy':{'min_target_r':MIN_TARGET_R,'max_estimated_cost_r':MAX_COST_R,
                              'max_cards_per_day':MAX_PER_DAY,'max_ticker_per_day':MAX_PER_TICKER_DAY},
            'cards':chosen,'scoring_policy':{'baseline':'day_move >= 0 AND trend >= 0',
                 'random':'1000 seeded subsets matched to Jo TAKE count per session and spec',
                 'execution':'independent frozen signals; factory next-open fills/exits/costs; no position suppression',
                 'reveal':'score only after every card has a recorded decision',
                 'warning':'five discovery sessions are development evidence; no profitability claim'}}
    private={'nonce':secrets.token_hex(32),'outcomes':{c['id']:outcomes[c['id']] for c in chosen}}
    public['sealed_outcomes_sha256']=digest(private)
    atomic(batch/'operator-private/outcomes.json',private)
    (batch/'operator-private').chmod(0o700)
    (batch/'operator-private/outcomes.json').chmod(0o600)
    atomic(batch/'operator-private/manifest.json',public)
    (batch/'operator-private/manifest.json').chmod(0o600)
    atomic(batch/'public/manifest.json',{'schema':VERSION,'cards':len(chosen),
           'manifest_sha256':digest(public),'notice':'Sequential reveal only; request view, then commit before next view'})
    quality={'schema':VERSION,'status':'awaiting Jo choices; no selection value measured',
             'sessions':[str(d) for d in DAYS],'raw_setups_per_session':dict(raw_counts),
             'geometry_rejections_per_session':dict(rejected),'cards_per_session':dict(Counter(c['simulated_as_of'][:10] for c in chosen)),
             'families':dict(Counter(c['setup'] for c in chosen)),
             'tickers':dict(Counter(c['candidate']['ticker'] for c in chosen)),
             'total_cards':len(chosen),'options_liquidity':'unavailable; cannot establish option eligibility',
             'source_specs':list(IDS),'old_factory_gates':'unchanged; these remain failed-screen strategies',
             'selection_policy':'fixed geometry + day/spec quotas + seeded sampling; no outcome ranking',
             'public_manifest_sha256':digest(public)}
    atomic(batch/'quality.json',quality)
    return quality


def view(batch):
    public=json.loads((batch/'operator-private/manifest.json').read_text())
    path=batch/'decisions.jsonl'
    with (batch/'decisions.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        previous={r['id']:r for r in map(json.loads,path.read_text().splitlines())} if path.exists() else {}
        if any(r.get('manifest_sha256')!=digest(public) for r in previous.values()):
            raise ValueError('Frozen manifest changed')
        next_card=next((c for c in public['cards'] if c['id'] not in previous),None)
        if next_card is None:
            response={'status':'all choices committed; operator may score'}
        else:
            response={'card':next_card,'manifest_sha256':digest(public),
                      'card_sha256':digest(next_card),'committed':len(previous),'total':len(public['cards'])}
            served=batch/'served.jsonl'
            marks={r['id']:r for r in map(json.loads,served.read_text().splitlines())} if served.exists() else {}
            if next_card['id'] not in marks:
                with served.open('a') as handle:
                    handle.write(canonical({'id':next_card['id'],'manifest_sha256':digest(public),
                        'card_sha256':digest(next_card),'served_at':datetime.now(search.ET).isoformat()})+'\n')
                    handle.flush()
                    os.fsync(handle.fileno())
        atomic(batch/'public/current-setup.json',response)
        return response


def decide(batch, source):
    public=json.loads((batch/'operator-private/manifest.json').read_text())
    ids={c['id'] for c in public['cards']}
    # Caller supplies Jo-authored choices; this local import is not identity authentication.
    choices=json.loads(source.read_text())
    if not isinstance(choices,list):
        raise ValueError('Choices must be a list')
    path=batch/'decisions.jsonl'
    with (batch/'decisions.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        previous={r['id']:r for r in map(json.loads,path.read_text().splitlines())} if path.exists() else {}
        served=batch/'served.jsonl'
        marks={r['id']:r for r in map(json.loads,served.read_text().splitlines())} if served.exists() else {}
        pending={}
        for row in choices:
            if set(row)!={'id','decision','reason'} or row['id'] not in ids or row['decision'] not in ('take','skip','insufficient_data') or not isinstance(row['reason'],str) or not 1<=len(row['reason'].strip())<=1000:
                raise ValueError('Unknown card or invalid choice')
            old=previous.get(row['id']) or pending.get(row['id'])
            if old and any(old[k]!=row[k] for k in row):
                raise ValueError('Immutable choice conflicts')
            if not old:
                next_card=next(c for c in public['cards'] if c['id'] not in previous and c['id'] not in pending)
                mark=marks.get(row['id'],{})
                if row['id']!=next_card['id'] or mark.get('manifest_sha256')!=digest(public) or mark.get('card_sha256')!=digest(next_card):
                    raise ValueError('Read and commit only the next chronological setup')
                pending[row['id']]={**row,'received_at':datetime.now(search.ET).isoformat(),
                'source':'operator import; Jo identity not authenticated','manifest_sha256':digest(public)}
        with path.open('a') as handle:
            for row in pending.values():
                handle.write(canonical(row)+'\n')
            handle.flush()
            os.fsync(handle.fileno())
    return len(pending)


def summary(ids,outcomes):
    resolved=[outcomes[i]['r'] for i in ids if outcomes[i]['resolved']]
    return {'selected':len(ids),'resolved':len(resolved),'total_r':sum(resolved) if resolved else None,
            'mean_r':sum(resolved)/len(resolved) if resolved else None}


def score(batch):
    public=json.loads((batch/'operator-private/manifest.json').read_text())
    choices={r['id']:r for r in map(json.loads,(batch/'decisions.jsonl').read_text().splitlines())}
    cards=public['cards']
    ids={c['id'] for c in cards}
    if not ids or set(choices)!=ids or any(r.get('manifest_sha256')!=digest(public) for r in choices.values()):
        raise ValueError('Complete unchanged frozen batch before revealing outcomes')
    private=json.loads((batch/'operator-private/outcomes.json').read_text())
    if digest(private)!=public['sealed_outcomes_sha256']:
        raise ValueError('Outcome seal mismatch')
    outcomes=private['outcomes']
    take=[c['id'] for c in cards if choices[c['id']]['decision']=='take']
    baseline=[c['id'] for c in cards if (c['features'].get('day_move') is not None and c['features']['day_move']>=0)
              and (c['features'].get('trend') is not None and c['features']['trend']>=0)]
    groups=defaultdict(list)
    counts=Counter()
    for c in cards:
        key=(c['simulated_as_of'][:10],c['candidate']['spec_id'])
        groups[key].append(c['id'])
        if c['id'] in take:
            counts[key]+=1
    rng=random.Random(SEED)
    random_totals=[]
    for _ in range(1000):
        sample=[i for key,group in sorted(groups.items()) for i in rng.sample(group,counts[key])]
        random_totals.append(sum(outcomes[i]['r'] for i in sample if outcomes[i]['resolved']))
    result={'schema':VERSION,'decisions':dict(Counter(r['decision'] for r in choices.values())),
            'take_all':summary(sorted(ids),outcomes),'jo_take':summary(take,outcomes),
            'fixed_context_filter':summary(baseline,outcomes),
            'matched_count_random':{'mean_total_r':sum(random_totals)/len(random_totals),
                'descriptive_percentile':sum(value<=sum(outcomes[i]['r'] for i in take if outcomes[i]['resolved']) for value in random_totals)/len(random_totals) if take else None},
            'warning':'development only; five sessions, correlated setups, no significance or options-performance claim'}
    atomic(batch/'selection-score.json',result)
    return result


def budgeted_build():
    if ROOT!=Path('/Users/user/TradeJournal-factory'):
        raise ValueError('Mac factory checkout only')
    import subprocess
    if subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()!='factory/ledger':
        raise ValueError('factory/ledger required')
    with (search.OUT/'writer.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        week=search.DEFAULT_OUT/'week.lock'
        week.mkdir()
        (week/'search-pid').write_text(str(os.getpid()))
        started=time.monotonic()
        budget=search.OUT/f'{search.night_key(datetime.now(search.ET))}-seconds.json'
        used=json.loads(budget.read_text()) if budget.exists() else 0
        allocation=min(900,search.SECONDS_CAP-used)
        try:
            if BATCH.exists():
                raise ValueError('Pilot already frozen')
            if allocation<60:
                raise ValueError('Existing time budget exhausted; do not reset it')
            atomic(budget,used+allocation)
            signal.signal(signal.SIGALRM,signal.SIG_DFL)
            signal.alarm(allocation)
            quality=build()
            signal.alarm(0)
            atomic(budget,used+min(allocation,math.ceil(time.monotonic()-started)))
            quality['runtime_seconds']=math.ceil(time.monotonic()-started)
            atomic(ROOT/'research/reports/2026-10-15-opportunity-pilot-v2.json',quality)
            print(json.dumps(quality,indent=2))
        finally:
            (week/'search-pid').unlink(missing_ok=True)
            week.rmdir()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['build','view','decide','score'])
    parser.add_argument('--choices',type=Path)
    args=parser.parse_args()
    if args.command=='build':
        budgeted_build()
    elif args.command=='view':
        print(json.dumps(view(BATCH),indent=2))
    elif args.command=='decide':
        if args.choices is None:
            parser.error('--choices is required')
        print(decide(BATCH,args.choices))
    else:
        print(json.dumps(score(BATCH),indent=2))
