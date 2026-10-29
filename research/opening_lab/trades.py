"""Trade mode: Claude enters or waits, then manages one trade, graded like a
short-dated option.

Clock. Entry checkpoints are 09:30-10:00 every five minutes (``ENTRY_CHECKPOINTS``).
While flat, Claude answers WAIT, LONG or SHORT (SPY or QQQ); at most one trade per
morning. Once in, it is asked again every five minutes, HOLD or EXIT, until it exits
or the trade reaches ``MAX_HOLD_MINUTES`` (forced exit). The last possible re-check
is 10:25.

Prices. "Price at time T" is the OPEN of the minute bar starting at T, or the CLOSE
of the bar ending at T when that bar is missing. Entry decided at checkpoint C fills
at C + 1 minute (as in the forecast contract); an EXIT at checkpoint E fills at
E + 1 minute; the forced exit fills at entry + ``MAX_HOLD_MINUTES``.

Grading (``OPTION_*``). A long call/put on SPY or QQQ only pays when the underlying
moves your way by more than the option's round-trip spread plus the time decay
while held. Net = side * move_bps - OPTION_SPREAD_BPS - OPTION_DECAY_BPS_PER_MIN *
minutes held, in basis points of the underlying. The constants approximate an
at-the-money, same-day expiry option (about delta 0.5): a ~$0.01-0.03 bid/ask on a
~$2-3 premium, and a premium that decays roughly with the square root of the time
left. They are assumptions, not option quotes; gamma (convexity on big moves) is
ignored, which understates large winners. A morning without a trade scores 0.

Packets (``build_trade_packet``) reuse ``packet.py``'s causal blocks: bars that
ended by the checkpoint, news by ``created_at <= C - 60 s``, scheduled macro times.
The full variant adds the ``cross`` section (``cross.py``).

Benchmarks need no model calls: each rule in ``baselines.py`` takes its first
non-WAIT signal and holds ``FIXED_HOLD_MINUTES``; Claude's own entries are also
graded with a fixed 15-minute exit and held to the maximum, which separates entry
skill from exit skill; and no trade at all.
"""

from datetime import date

from . import packet as pk
from .baselines import BASELINES
from .contract import (CHECKPOINTS_ET, SYMBOLS, VARIANTS, checkpoint_ts, et_hhmm,
                       validate_forecast, visible_bars)
from .cross import cross_block
from .evaluate import BOOTSTRAP_DRAWS, BOOTSTRAP_SEED, _diff_block

VERSION = "opening-lab-trade-v1"
ENTRY_CHECKPOINTS = CHECKPOINTS_ET
MAX_HOLD_MINUTES = 30
FIXED_HOLD_MINUTES = 15
CHECKPOINTS = ENTRY_CHECKPOINTS + ("10:05", "10:10", "10:15", "10:20", "10:25")
OPTION_SPREAD_BPS = 2.0
OPTION_DECAY_BPS_PER_MIN = 0.15
ENTRY_ACTIONS = ("WAIT", "LONG", "SHORT")
MANAGE_ACTIONS = ("HOLD", "EXIT")

# Structured-output schema (no numeric/string bounds; checked by validate_decision).
TRADE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "symbol", "reason"],
    "properties": {
        "action": {"type": "string", "enum": list(ENTRY_ACTIONS + MANAGE_ACTIONS)},
        "symbol": {"anyOf": [{"type": "string", "enum": list(SYMBOLS)}, {"type": "null"}],
                   "description": "SPY or QQQ for LONG/SHORT; null otherwise."},
        "reason": {"type": "string", "description": "At most 400 characters."},
    },
}


def validate_decision(value):
    """Normalized decision dict, or ValueError naming the defect."""
    if not isinstance(value, dict) or set(value) != {"action", "symbol", "reason"}:
        raise ValueError("decision_fields")
    action, symbol, reason = value["action"], value["symbol"], value["reason"]
    if action not in ENTRY_ACTIONS + MANAGE_ACTIONS:
        raise ValueError("decision_action")
    if action in ("LONG", "SHORT"):
        if symbol not in SYMBOLS:
            raise ValueError("decision_trade_symbol")
    else:
        symbol = None  # a symbol on WAIT/HOLD/EXIT carries no meaning
    if not isinstance(reason, str) or len(reason) > 400:
        raise ValueError("decision_reason")
    return {"action": action, "symbol": symbol, "reason": reason}


# Clock and state ---------------------------------------------------------------
def _entry_ts(day, entry_cp):
    return checkpoint_ts(day, entry_cp) + 60


def _forced_exit_ts(day, entry_cp):
    return _entry_ts(day, entry_cp) + MAX_HOLD_MINUTES * 60


def position_from(decisions):
    """Trade implied by (checkpoint, decision-or-None) pairs in order, or None.

    A missing/failed/invalid answer counts as WAIT (flat) or HOLD (in a trade)."""
    trade = None
    for cp, d in decisions:
        if trade is None:
            if d and d["action"] in ("LONG", "SHORT") and cp in ENTRY_CHECKPOINTS:
                trade = {"symbol": d["symbol"], "side": d["action"], "entry_cp": cp, "exit_cp": None}
        elif trade["exit_cp"] is None and d and d["action"] == "EXIT":
            trade["exit_cp"] = cp
    return trade


def phase_at(day, cp, trade):
    """'entry', 'manage', or None when nothing more is asked this morning."""
    if trade is None:
        return "entry" if cp in ENTRY_CHECKPOINTS else None
    if trade["exit_cp"] is not None or cp <= trade["entry_cp"]:
        return None
    return "manage" if checkpoint_ts(day, cp) + 60 < _forced_exit_ts(day, trade["entry_cp"]) else None


def walk(day, answer):
    """Run the morning: ``answer(cp, phase, trade, decisions)`` returns the decision
    (or None) at each asked checkpoint. Returns (trade, decisions)."""
    decisions = []
    for cp in CHECKPOINTS:
        trade = position_from(decisions)
        phase = phase_at(day, cp, trade)
        if phase is None:  # past the entry window, exited, or at the forced exit
            break
        decisions.append((cp, answer(cp, phase, trade, decisions)))
    return position_from(decisions), decisions


def check_phase(decision, phase):
    """True when the action is allowed in the phase."""
    return decision["action"] in (ENTRY_ACTIONS if phase == "entry" else MANAGE_ACTIONS)


# Prices and grading ------------------------------------------------------------
def _bars_by_t(session, symbol):
    return {b["t"]: b for b in ((session.get("symbols") or {}).get(symbol) or {}).get("minutes") or []}


def price_at(by_t, ts):
    bar = by_t.get(ts)
    if bar is not None:
        return bar["o"]
    before = by_t.get(ts - 60)
    return before["c"] if before is not None else None


def grade(session, trade, *, exit_kind="model"):
    """Graded trade dict, or None when a price is missing.

    exit_kind: "model" (its EXIT, else forced), "fixed" (FIXED_HOLD_MINUTES) or
    "max" (held to MAX_HOLD_MINUTES)."""
    day = session["date"]
    by_t = _bars_by_t(session, trade["symbol"])
    entry_ts = _entry_ts(day, trade["entry_cp"])
    if exit_kind == "fixed":
        exit_ts, how = entry_ts + FIXED_HOLD_MINUTES * 60, "fixed"
    elif exit_kind == "model" and trade.get("exit_cp"):
        exit_ts, how = checkpoint_ts(day, trade["exit_cp"]) + 60, "model"
    else:
        exit_ts, how = _forced_exit_ts(day, trade["entry_cp"]), "max"
    entry, out = price_at(by_t, entry_ts), price_at(by_t, exit_ts)
    if entry is None or out is None:
        return None
    sign = 1 if trade["side"] == "LONG" else -1
    gross = sign * (out / entry - 1) * 1e4
    minutes = (exit_ts - entry_ts) // 60
    return {"symbol": trade["symbol"], "side": trade["side"], "entry_et": et_hhmm(entry_ts),
            "exit_et": et_hhmm(exit_ts), "exit": how, "minutes": minutes,
            "gross_bps": round(gross, 3),
            "net_bps": round(gross - OPTION_SPREAD_BPS - OPTION_DECAY_BPS_PER_MIN * minutes, 3)}


# Packets -----------------------------------------------------------------------
def _position(session, c_ts, trade):
    day = session["date"]
    entry_ts = _entry_ts(day, trade["entry_cp"])
    seen = visible_bars((session["symbols"].get(trade["symbol"]) or {}).get("minutes") or [], c_ts)
    by_t = {b["t"]: b for b in seen}
    entry = price_at(by_t, entry_ts)
    last = seen[-1]["c"] if seen else None
    sign = 1 if trade["side"] == "LONG" else -1
    move = sign * (last / entry - 1) * 1e4 if entry and last else None
    held = (c_ts - entry_ts) // 60
    return {"side": trade["side"], "symbol": trade["symbol"], "entry_et": et_hhmm(entry_ts),
            "entry_price": pk._price(entry), "last": pk._price(last),
            "move_bps": None if move is None else round(move, 2),
            "option_net_bps_if_exit_now": None if move is None else round(
                move - OPTION_SPREAD_BPS - OPTION_DECAY_BPS_PER_MIN * (held + 1), 2),
            "minutes_held": held,
            "forced_exit_et": et_hhmm(_forced_exit_ts(day, trade["entry_cp"]))}


def build_trade_packet(session, checkpoint_et, variant, decisions=(), trade=None):
    """Causal packet for one trade-mode checkpoint (``decisions``: earlier
    (checkpoint, decision-or-None) pairs; ``trade``: the open trade or None)."""
    if checkpoint_et not in CHECKPOINTS:
        raise ValueError(f"checkpoint:{checkpoint_et}")
    if variant not in VARIANTS:
        raise ValueError(f"variant:{variant}")
    day = session["date"]
    schedule = session.get("schedule") or {}
    open_ts = checkpoint_ts(day, schedule.get("open") or "09:30")
    c_ts = checkpoint_ts(day, checkpoint_et)
    if any(cp >= checkpoint_et for cp, _ in decisions):
        raise ValueError("decision_not_earlier")
    full = variant == "full"
    symbols = session.get("symbols") or {}
    return {
        "version": VERSION,
        "variant": variant,
        "checkpoint_et": checkpoint_et,
        "phase": "manage" if trade else "entry",
        "weekday": date.fromisoformat(day).strftime("%A"),
        "minutes_since_open": (c_ts - open_ts) // 60,
        "early_close": bool(schedule.get("early_close", False)),
        "symbols": {s: pk._symbol_block(symbols.get(s), day, open_ts, c_ts, variant) for s in SYMBOLS},
        "cross": cross_block(session, c_ts) if full else None,
        "news": pk._news(session.get("news"), c_ts) if full else [],
        "macro": pk._macro(session.get("macro"), day, c_ts) if full else [],
        "position": _position(session, c_ts, trade) if trade else None,
        "earlier": [{"checkpoint_et": cp, "action": d["action"] if d else None,
                     "symbol": d["symbol"] if d else None} for cp, d in decisions],
    }


# Model driver ------------------------------------------------------------------
def replay(run_dir, days, *, sessions, model, model_name, variants=VARIANTS, workers=2,
           max_cost_usd=None, log=print):
    """Ask ``model`` through each morning and variant; resumable like ``runner.replay``."""
    from concurrent.futures import ThreadPoolExecutor

    from .runner import MAX_ERRORS_PER_INVOCATION, RETRYABLE, Budget, Run, _record, source_fingerprint

    run = Run(run_dir, {
        "kind": "trade", "days": list(days), "variants": list(variants), "model": model_name,
        "model_settings": getattr(model, "settings", None), "source": source_fingerprint(),
        "contract": {"entry_checkpoints": ENTRY_CHECKPOINTS, "checkpoints": CHECKPOINTS,
                     "max_hold": MAX_HOLD_MINUTES, "fixed_hold": FIXED_HOLD_MINUTES,
                     "spread_bps": OPTION_SPREAD_BPS, "decay_bps_per_min": OPTION_DECAY_BPS_PER_MIN},
    })
    budget = Budget(max_cost_usd, run.rows())

    def chain(day, variant):
        state = {"redo": False, "stopped": False}

        def answer(cp, phase, trade, decisions):
            key = (day, cp, model_name, variant)
            row = run.records.get(key)
            if row is None or state["redo"] or row["status"] in RETRYABLE:
                if not budget.open():
                    state["stopped"] = True
                    return None
                packet = build_trade_packet(sessions[day], cp, variant, decisions, trade)
                result = model.forecast(packet)
                if result["status"] == "ok" and not check_phase(result["forecast"], phase):
                    result = {**result, "status": "invalid", "forecast": None,
                              "error": f"phase_{phase}_{result['forecast']['action']}"}
                new = _record(day, cp, model_name, variant, packet, result)
                budget.charge(new)
                state["redo"] = state["redo"] or row is not None and new["status"] == "ok"
                row = new
                run.add(row, packet)
            return row["forecast"] if row["status"] == "ok" else None

        walk(day, answer)
        return "budget" if state["stopped"] else "done"

    jobs = [(d, v) for d in days for v in variants]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        outcomes = list(pool.map(lambda job: chain(*job), jobs))
    if "budget" in outcomes:
        if budget.errors >= MAX_ERRORS_PER_INVOCATION:
            log(f"Stopped after {budget.errors} provider errors; re-run the same command to retry them.")
        else:
            log(f"Stopped at the cost cap: ${budget.spent:.2f} recorded in this run directory.")
    return run


class FakeTrader:
    """Deterministic stand-in (no calls): long SPY at 09:40, exit at the 3rd re-check."""

    model, backend = "fake-trader", "fake"

    def forecast(self, packet):
        if packet["phase"] == "entry":
            d = {"action": "LONG", "symbol": "SPY", "reason": "fake"} if packet["checkpoint_et"] >= "09:40" \
                else {"action": "WAIT", "symbol": None, "reason": "fake"}
        else:
            d = {"action": "EXIT" if packet["position"]["minutes_held"] >= 14 else "HOLD",
                 "symbol": None, "reason": "fake"}
        return {"status": "ok", "forecast": validate_decision(d), "error": None, "latency_s": 0.0,
                "cost_usd": 0.0, "cache_hit": False}


# Scoring -----------------------------------------------------------------------
def _rule_trade(session, fn):
    for cp in ENTRY_CHECKPOINTS:
        try:
            f = validate_forecast(fn(pk.build_packet(session, cp, "market")))
        except Exception:
            continue
        if f["action"] != "WAIT":
            return {"symbol": f["symbol"], "side": f["action"], "entry_cp": cp, "exit_cp": None}
    return None


def _model_mornings(rows):
    """{(agent, variant): {day: {cp: row}}} from trade-run records."""
    out = {}
    for r in rows:
        out.setdefault((r["agent"], r["variant"]), {}).setdefault(r["date"], {})[r["checkpoint_et"]] = r
    return out


def _summary(results):
    """results: {day: graded dict, "none", or None (unscorable)}."""
    graded = [g for g in results.values() if isinstance(g, dict)]
    scorable = [g for g in results.values() if g is not None]
    nets = [g["net_bps"] for g in graded]

    def mean(xs):
        return round(sum(xs) / len(xs), 3) if xs else None

    return {
        "mornings": len(scorable), "trades": len(graded),
        "pays": mean([n > 0 for n in nets]),
        "right_direction": mean([g["gross_bps"] > 0 for g in graded]),
        "net_per_trade": mean(nets),
        "net_per_morning": mean([g["net_bps"] if isinstance(g, dict) else 0.0 for g in scorable]),
        "minutes": mean([g["minutes"] for g in graded]),
        "own_exits": sum(g["exit"] == "model" for g in graded),
        "long_share": mean([g["side"] == "LONG" for g in graded]),
    }


def _morning_value(g):
    return None if g is None else (g["net_bps"] if isinstance(g, dict) else 0.0)


def score_trades(rows, sessions, *, rules=None, draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED):
    """Score trade-run records (one or several runs) and the benchmarks."""
    # coin never trades, so it would duplicate "no trade"
    rules = {k: v for k, v in BASELINES.items() if k != "coin"} if rules is None else rules
    days = sorted(sessions)
    strategies, models, asks = {}, [], {}

    def graded(trade, session, kind):
        if trade is None:
            return "none"
        return grade(session, trade, exit_kind=kind)

    for (agent, variant), by_day in sorted(_model_mornings(rows).items()):
        name = f"{agent}/{variant}"
        models.append(name)
        own, fixed, held, n_asks, failed = {}, {}, {}, 0, 0
        for day in days:
            got = by_day.get(day, {})

            def answer(cp, phase, trade, decisions, got=got):
                row = got.get(cp)
                return row["forecast"] if row and row["status"] == "ok" else None

            trade, decisions = walk(day, answer)
            n_asks += len(decisions)
            failed += sum(1 for cp, _ in decisions if (got.get(cp) or {}).get("status") != "ok")
            own[day] = graded(trade, sessions[day], "model")
            fixed[day] = graded(trade, sessions[day], "fixed")
            held[day] = graded(trade, sessions[day], "max")
        strategies[name] = own
        strategies[f"{name} entries, exit {FIXED_HOLD_MINUTES}m"] = fixed
        strategies[f"{name} entries, hold {MAX_HOLD_MINUTES}m"] = held
        asks[name] = {"asked": n_asks, "not_ok": failed}

    for rule, fn in sorted(rules.items()):
        strategies[f"rule {rule}, exit {FIXED_HOLD_MINUTES}m"] = {
            d: graded(_rule_trade(sessions[d], fn), sessions[d], "fixed") for d in days}
    strategies["no trade"] = {d: "none" for d in days}

    def diff(a, b):
        per = {}
        for d in days:
            va, vb = _morning_value(strategies[a][d]), _morning_value(strategies[b][d])
            per[d] = (va - vb, 1) if va is not None and vb is not None else (0.0, 0)
        return _diff_block(per, False, draws, seed, "bps per morning")

    comparisons = []
    for m in models:
        agent, variant = m.rsplit("/", 1)
        others = [f"{m} entries, exit {FIXED_HOLD_MINUTES}m", f"{m} entries, hold {MAX_HOLD_MINUTES}m",
                  "no trade"] + [s for s in strategies if s.startswith("rule ")]
        others += [o for o in models if o != m and o > m and
                   (o.rsplit("/", 1)[0] == agent or o.rsplit("/", 1)[1] == variant)]
        comparisons += [{"a": m, "b": o, **diff(m, o)} for o in others]

    return {
        "meta": {"n_sessions": len(days), "max_hold_min": MAX_HOLD_MINUTES, "fixed_hold_min": FIXED_HOLD_MINUTES,
                 "spread_bps": OPTION_SPREAD_BPS, "decay_bps_per_min": OPTION_DECAY_BPS_PER_MIN},
        "strategies": {name: _summary(res) for name, res in strategies.items()},
        "asks": asks,
        "trades": {m: {d: g for d, g in strategies[m].items() if isinstance(g, dict)} for m in models},
        "comparisons": comparisons,
    }


def render_trades(report):
    m = report["meta"]
    lines = [f"Opening lab trade scorecard - {m['n_sessions']} mornings; option cost "
             f"{m['spread_bps']} bp + {m['decay_bps_per_min']} bp/min held; max hold {m['max_hold_min']}m",
             ""]
    width = max(len(n) for n in report["strategies"]) + 1
    head = (f"{'strategy':<{width}}{'mornings':>9}{'trades':>7}{'pays':>6}{'right':>7}"
            f"{'net/trade':>10}{'net/morning':>12}{'min':>6}{'own exits':>10}{'long':>6}")
    lines += [head, "-" * len(head)]

    def f(x, nd=2):
        return "-" if x is None else f"{x:.{nd}f}"

    for name, s in report["strategies"].items():
        lines.append(f"{name:<{width}}{s['mornings']:>9}{s['trades']:>7}{f(s['pays']):>6}"
                     f"{f(s['right_direction']):>7}{f(s['net_per_trade']):>10}{f(s['net_per_morning']):>12}"
                     f"{f(s['minutes'], 1):>6}{s['own_exits']:>10}{f(s['long_share']):>6}")
    if report["asks"]:
        lines += ["", "Model answers: " + "; ".join(f"{k}: {v['asked']} asked, {v['not_ok']} not ok"
                                                   for k, v in report["asks"].items())]
    lines += ["", "Paired per-morning comparisons (A - B, bps per morning; session bootstrap 95% CI):"]
    for c in report["comparisons"]:
        ci = c["ci95"] or [None, None]
        lines.append(f"  {c['a']}  vs  {c['b']}: {f(c['diff_a_minus_b'])} CI [{f(ci[0])}, {f(ci[1])}] "
                     f"MDE {f(c['min_detectable_effect'])} -> {c['verdict']}")
    lines += ["", "Notes: net is in basis points of the underlying after an assumed option spread and decay "
                  "(not option quotes; convexity ignored). 'pays' = share of trades with net > 0; 'right' = "
                  "share that moved the chosen way before costs. A morning without a trade scores 0."]
    return "\n".join(lines)
