"""Import a frozen Mac opportunity pilot into the isolated sequential replay.

No factory execution, provider access, model call or live scanner mutation.
Only the guarded operator may import precomputed, committed underlying results.
"""

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import random
import re
import secrets
import uuid

from app.engine import decisions

KIND = "opportunity_feed"
VERSION = "factory-opportunity-selection-v1"
SYMBOLS = frozenset(
    (
        "NBIS",
        "MU",
        "META",
        "AAPL",
        "AMD",
        "LLY",
        "TSLA",
        "GOOG",
        "AMZN",
        "NFLX",
        "NVDA",
        "MSFT",
        "AVGO",
        "COIN",
        "GS",
        "CAT",
        "MRVL",
        "PLTR",
    )
)
POLICY = {
    "version": VERSION,
    "execution": "sealed factory underlying outcomes; no recomputation",
    "baseline": "day_move >= 0 AND trend >= 0",
    "random": "1000 seeded subsets matched to TAKE count per session and spec",
    "decision_delay_seconds": None,
    "options_performance": "unavailable",
}
PROMPT = (
    "Act as Trader Jo in an offline opportunity-selection development pilot. "
    "Use only this assigned replay and its next_setup. Read its frozen card, then commit "
    "TAKE, SKIP or INSUFFICIENT_DATA with a reason <=1000 characters. Do not change entries/exits. "
    "After each commit read the same run for the next chronological card; resume interruptions "
    "with get_practice_run(resume=true). No later card or outcome is available before earlier choices. "
    "All five sessions must be committed before the report reveals. Assess underlying setups; "
    "historical option quotes/spreads/eligibility and trade history are unavailable, not failed liquidity checks. "
    "Do not invent historical news, option performance or same-day knowledge. No other trading, "
    "journal, mail or co-pilot tools. This is discovery development, not an exam or live trading."
)
SOURCE_POLICY = {
    "baseline": "day_move >= 0 AND trend >= 0",
    "execution": "independent frozen signals; factory next-open fills/exits/costs; no position suppression",
    "random": "1000 seeded subsets matched to Jo TAKE count per session and spec",
    "reveal": "score only after every card has a recorded decision",
    "warning": "five discovery sessions are development evidence; no profitability claim",
}
CARD_KEYS = {
    "id",
    "schema",
    "candidate",
    "family",
    "setup",
    "timeframe_minutes",
    "simulated_as_of",
    "entry_reference",
    "stop",
    "target_reference",
    "target_r",
    "max_minutes",
    "features",
    "estimated_round_trip_cost_r",
    "option_eligibility",
    "candles",
    "source",
    "labels",
}
FEATURES = frozenset(
    (
        "minutes",
        "rvol",
        "gap",
        "day_move",
        "trend",
        "trend_slope",
        "rel_strength",
        "spy_trend",
        "spy_day",
        "risk",
        "vwap_distance",
        "vol_ratio",
        "spy_vol",
        "open_trend",
        "prior_day_high",
        "prior_day_low",
        "prior_day_close",
        "prior_week_high",
        "prior_week_low",
        "opening_range_high",
        "opening_range_low",
        "swing_high",
        "swing_low",
    )
)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def number(value, *, positive=False):
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or (positive and value <= 0)
    ):
        raise ValueError("Expected a finite number")
    return float(value)


def stamp(value):
    if not isinstance(value, str):
        raise ValueError("Expected timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp must include zone")
    return result


def validate(bundle):
    if (
        not isinstance(bundle, dict)
        or set(bundle) != {"format", "manifest", "outcomes"}
        or bundle["format"] != "opportunity-replay-import-v1"
    ):
        raise ValueError("Unrecognized opportunity import")
    source, private = bundle["manifest"], bundle["outcomes"]
    expected = {
        "schema",
        "frozen_at",
        "sessions",
        "seed",
        "spec_ids",
        "quality_policy",
        "cards",
        "scoring_policy",
        "sealed_outcomes_sha256",
    }
    if (
        set(source) != expected
        or source["schema"] != "opportunity-pilot-v1"
        or type(source["seed"]) is not int
    ):
        raise ValueError("Unrecognized frozen pilot manifest")
    days = [date.fromisoformat(day) for day in source["sessions"]]
    if (
        not 1 <= len(days) <= 30
        or days != sorted(set(days))
        or days[-1] > date(2024, 9, 30)
    ):
        raise ValueError("Opportunity pilot is discovery-only")
    stamp(source["frozen_at"])
    if source["scoring_policy"] != SOURCE_POLICY:
        raise ValueError("Unrecognized source scoring policy")
    if source["quality_policy"] != {
        "min_target_r": 1.25,
        "max_estimated_cost_r": 0.25,
        "max_cards_per_day": 18,
        "max_ticker_per_day": 3,
    }:
        raise ValueError("Unrecognized frozen admission policy")
    if (
        not isinstance(source["spec_ids"], list)
        or not 1 <= len(source["spec_ids"]) <= 24
        or any(
            not re.fullmatch(r"[a-z0-9]{2}-[0-9a-f]{10}", s) for s in source["spec_ids"]
        )
    ):
        raise ValueError("Invalid source spec IDs")
    if (
        not isinstance(private, dict)
        or set(private) != {"nonce", "outcomes"}
        or not isinstance(private["nonce"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", private["nonce"])
        or digest(private) != source["sealed_outcomes_sha256"]
    ):
        raise ValueError("Pilot outcome seal mismatch")
    cards = source["cards"]
    if not isinstance(cards, list) or not 1 <= len(cards) <= 200:
        raise ValueError("Bounded nonempty pilot required")
    if not isinstance(private["outcomes"], dict) or set(private["outcomes"]) != {
        c["id"] for c in cards
    }:
        raise ValueError("Exact outcome/card binding required")
    ids = set()
    shared = set()
    per_day = Counter()
    per_ticker = Counter()
    order = []
    for card in cards:
        if (
            not isinstance(card, dict)
            or set(card) != CARD_KEYS
            or card["schema"] != "opportunity-pilot-v1"
        ):
            raise ValueError("Unrecognized public card fields")
        if not re.fullmatch(r"[0-9a-f]{20}", card["id"]) or card["id"] in ids:
            raise ValueError("Duplicate/invalid card")
        ids.add(card["id"])
        candidate = card["candidate"]
        if (
            set(candidate) != {"spec_id", "ticker", "signal_time", "side"}
            or candidate["ticker"] not in SYMBOLS
            or candidate["spec_id"] not in source["spec_ids"]
            or type(candidate["side"]) is not int
            or candidate["side"] not in (-1, 1)
        ):
            raise ValueError("Invalid frozen candidate")
        if digest(candidate)[:20] != card["id"]:
            raise ValueError("Card identity mismatch")
        at = stamp(card["simulated_as_of"])
        signal = stamp(candidate["signal_time"])
        if (
            type(card["timeframe_minutes"]) is not int
            or card["timeframe_minutes"] not in (1, 2, 3, 5, 10, 15, 30)
            or at - signal != timedelta(minutes=card["timeframe_minutes"])
        ):
            raise ValueError("Signal/cutoff mismatch")
        from app.engine.market_map import ET

        day = at.astimezone(ET).date().isoformat()
        if (
            day not in source["sessions"]
            or signal.astimezone(ET).date() != at.astimezone(ET).date()
        ):
            raise ValueError("Session mismatch")
        order.append((at.astimezone(timezone.utc), candidate["ticker"], card["id"]))
        key = (candidate["ticker"], candidate["signal_time"], candidate["side"])
        if key in shared:
            raise ValueError("Duplicate shared opportunity")
        shared.add(key)
        per_day[day] += 1
        per_ticker[day, candidate["ticker"]] += 1
        if per_day[day] > 18 or per_ticker[day, candidate["ticker"]] > 3:
            raise ValueError("Pilot quota exceeded")
        if card["family"] not in (
            "s1_research",
            "opening_range_breakout",
            "vwap_reclaim",
            "failed_breakout",
            "recovery_swing",
        ) or card["setup"] not in (
            "orb",
            "fade",
            "opening_range_breakout",
            "vwap_reclaim",
            "failed_breakout",
            "recovery_swing",
        ):
            raise ValueError("Unknown research family")
        expected_setup = (
            {"orb", "fade"} if card["family"] == "s1_research" else {card["family"]}
        )
        if card["setup"] not in expected_setup:
            raise ValueError("Family/setup mismatch")
        reference = number(card["entry_reference"], positive=True)
        stop = number(card["stop"], positive=True)
        target = number(card["target_reference"], positive=True)
        r = number(card["target_r"], positive=True)
        risk = candidate["side"] * (reference - stop)
        if (
            risk <= 0
            or r < 1.25
            or not math.isclose(
                target,
                reference + candidate["side"] * r * risk,
                rel_tol=1e-9,
                abs_tol=1e-8,
            )
        ):
            raise ValueError("Invalid frozen geometry")
        cost = number(card["estimated_round_trip_cost_r"])
        if not 0 <= cost <= 0.25:
            raise ValueError("Invalid estimated underlying cost")
        if card["max_minutes"] is not None and (
            type(card["max_minutes"]) is not int or not 1 <= card["max_minutes"] <= 1440
        ):
            raise ValueError("Invalid fixed exit")
        if not isinstance(card["features"], dict) or set(card["features"]) - FEATURES:
            raise ValueError("Unexpected feature fields")
        for value in card["features"].values():
            if value is not None:
                number(value)
        if card["option_eligibility"] != {
            "available": False,
            "reason": "No historical option quotes, spreads or contract evidence",
        }:
            raise ValueError("Option eligibility must remain unknown")
        if card[
            "source"
        ] != "cached Alpaca SIP; retrospective data, may contain corrections" or card[
            "labels"
        ] != [
            "offline-research",
            "underlying-only",
            "independence-unverified",
            "options-liquidity-unverified",
            "split-adjusted-to-decision-basis",
        ]:
            raise ValueError("Unexpected provenance/labels")
        candles = card["candles"]
        last = None
        if not isinstance(candles, list) or not 1 <= len(candles) <= 60:
            raise ValueError("Bounded cutoff candles required")
        for bar in candles:
            if set(bar) != {"start", "end", "open", "high", "low", "close", "volume"}:
                raise ValueError("Unexpected candle fields")
            start, end = stamp(bar["start"]), stamp(bar["end"])
            if (
                end - start != timedelta(minutes=card["timeframe_minutes"])
                or end > at
                or (last is not None and start < last)
            ):
                raise ValueError("Future/overlapping candle")
            last = end
            o, h, lo, c = [
                number(bar[k], positive=True) for k in ("open", "high", "low", "close")
            ]
            if lo > min(o, c) or h < max(o, c) or lo > h or number(bar["volume"]) < 0:
                raise ValueError("Invalid candle")
        if last != at or not math.isclose(
            candles[-1]["close"], reference, rel_tol=1e-9
        ):
            raise ValueError("Cutoff reference mismatch")
        outcome = private["outcomes"][card["id"]]
        if set(outcome) != {"resolved", "r"} or type(outcome["resolved"]) is not bool:
            raise ValueError("Invalid sealed outcome")
        if outcome["resolved"]:
            number(outcome["r"])
        elif outcome["r"] is not None:
            raise ValueError("Unresolved outcome must remain unknown")
    if order != sorted(order):
        raise ValueError("Chronological cards required")
    return source, private


def prepare(db, bundle, identifier):
    from sqlmodel import select
    from app.engine import access, scanner_replay as replay
    from app.models import AccessPrincipal, DecisionContext, JobRun, PracticeRun

    source, private = validate(bundle)
    if not re.fullmatch(r"[a-z][a-z0-9_-]{2,63}", identifier) or identifier == "owner":
        raise ValueError("Fresh isolated actor required")
    if stamp(source["frozen_at"]).astimezone(timezone.utc) > access.now().replace(
        tzinfo=timezone.utc
    ):
        raise ValueError("Future freeze receipt")
    identity = digest(
        {
            "actor": identifier,
            "input": digest(bundle),
            "policy": POLICY,
            "prompt": PROMPT,
        }
    )
    day = source["sessions"][0]
    run_id = uuid.uuid5(uuid.NAMESPACE_URL, replay.PREFIX + identity)
    manifest = {
        "schema": replay.SCHEMA,
        "kind": KIND,
        "actor": identifier,
        "batch_id": identity,
        "run_ids": {day: str(run_id)},
        "phases": {day: "practice"},
        "seed": source["seed"],
        "exam_count": 0,
        "prompt_text": PROMPT,
        "prompt_version": VERSION,
        "scoring_policy": POLICY,
        "input_sha256": digest(bundle),
        "source_manifest_sha256": digest(source),
        "sessions": source["sessions"],
        "symbols": sorted({c["candidate"]["ticker"] for c in source["cards"]}),
    }
    previous = db.get(PracticeRun, run_id)
    if previous:
        if replay.metadata(previous)["manifest"] != manifest:
            raise ValueError("Frozen batch mismatch")
        return [previous]
    if db.get(AccessPrincipal, identifier) or any(
        replay.metadata(r)["manifest"]["actor"] == identifier
        for r in db.exec(
            select(PracticeRun).where(PracticeRun.session_key.startswith(replay.PREFIX))
        ).all()
    ):
        raise ValueError("Actor cannot be repointed")
    now = access.now()
    job = JobRun(
        job_type="opportunity_replay_import", status="running", total=1, done=0
    )
    try:
        db.add(job)
        db.flush()
        run = PracticeRun(
            id=run_id,
            session_key=replay.PREFIX + identity,
            day=date.fromisoformat(day),
            job_id=job.id,
            mode="manual",
            comparison="assisted",
            status="prepared",
            result="opportunity_selection_development",
            deadline=now + timedelta(days=30),
            policy_version=replay.SCHEMA,
            policy_hash=replay.digest(manifest),
        )
        db.add(run)
        db.flush()
        entries = []
        for index, card in enumerate(source["cards"]):
            cid = str(uuid.uuid5(run.id, card["id"]))
            oid = str(uuid.uuid5(run.id, cid))
            cutoff = card["simulated_as_of"]
            sealed = {
                "nonce": secrets.token_hex(32),
                "outcome": private["outcomes"][card["id"]],
            }
            packet = {
                "schema_version": replay.SCHEMA,
                "opportunity_id": oid,
                "replay_commitment": replay.digest(sealed),
                "candidate": {
                    "candidate_id": cid,
                    "symbol": card["candidate"]["ticker"],
                    "setup": card["setup"],
                    "direction": "long" if card["candidate"]["side"] == 1 else "short",
                    "detected_at": cutoff,
                    "session_date": stamp(cutoff)
                    .astimezone(decisions.ET)
                    .date()
                    .isoformat(),
                    "stop": card["stop"],
                    "target": card["target_reference"],
                },
                "opportunity": card,
                "history": {"available": False, "source_state": "missing"},
                "labels": card["labels"],
                "provider_retrieved_at": None,
                "dataset_frozen_at": source["frozen_at"],
            }
            context = DecisionContext(
                operation_id="scanner:" + oid,
                symbol=card["candidate"]["ticker"],
                provider="alpaca_sip",
                captured_at=now,
                data_json=replay.canonical(packet),
                context_sha256=replay.digest(packet),
            )
            db.add(context)
            db.flush()
            entries.append(
                {
                    "index": index,
                    "opportunity_id": oid,
                    "context_id": str(context.id),
                    "symbol": context.symbol,
                    "sealed": sealed,
                }
            )
        run.calendar_json = replay.canonical(
            {
                "session": {"development_sessions": source["sessions"]},
                "entries": entries,
            }
        )
        run.brief_json = replay.canonical(
            {
                "schema": replay.SCHEMA,
                "manifest": manifest,
                "phase": "practice",
                "differences": [
                    "Frozen factory opportunity pilot; not fixed S1 scanner",
                    "Independent signals, not portfolio execution",
                    "No historical option eligibility, delayed-entry simulation or news",
                    "Dataset freeze time is not provider retrieval time",
                ],
                "labels": [
                    "opportunity-feed-development",
                    "underlying-only",
                    "options-liquidity-unverified",
                    "independence-unverified",
                ],
                "retrieved_at": source["frozen_at"],
                "coverage_gaps": [],
                "coverage": {
                    "provider_retrieval_time": "unknown",
                    "minute_completeness": "unverified",
                },
                "daily_atr": None,
                "calendar_sha256": decisions._hash(run.calendar_json),
            }
        )
        job.status = "succeeded"
        job.done = 1
        job.finished_at = now
        db.add(run)
        db.add(job)
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return [run]


def score_rows(db, run):
    from app.engine import scanner_replay as replay

    meta = replay.metadata(run)
    records = replay.own_records(db, run, meta["manifest"]["actor"])
    rows = []
    for entry in replay.entries(run):
        _, packet = replay.context_packet(db, entry)
        record = records.get(replay.operation(run, entry))
        rows.append(
            {
                "opportunity_id": entry["opportunity_id"],
                "candidate": packet["candidate"],
                "card": packet["opportunity"],
                "choice": replay.receipt(record) if record else None,
                "outcome": entry["sealed"]["outcome"],
            }
        )
    return rows


def report(rows, seed):
    def summary(chosen):
        resolved = [r["outcome"]["r"] for r in chosen if r["outcome"]["resolved"]]
        return {
            "selected": len(chosen),
            "resolved": len(resolved),
            "unresolved": len(chosen) - len(resolved),
            "total_r": sum(resolved) if resolved else None,
            "mean_r": sum(resolved) / len(resolved) if resolved else None,
        }

    take = [r for r in rows if (r["choice"] or {}).get("decision") == "take"]
    baseline = [
        r
        for r in rows
        if all(
            r["card"]["features"].get(k) is not None and r["card"]["features"][k] >= 0
            for k in ("day_move", "trend")
        )
    ]
    groups = defaultdict(list)
    counts = Counter()
    for row in rows:
        key = (row["card"]["simulated_as_of"][:10], row["card"]["candidate"]["spec_id"])
        groups[key].append(row)
        if (row["choice"] or {}).get("decision") == "take":
            counts[key] += 1
    rng = random.Random(seed)
    totals = []
    for _ in range(1000):
        sample = [
            r
            for key, group in sorted(groups.items())
            for r in rng.sample(group, counts[key])
        ]
        totals.append(
            sum(r["outcome"]["r"] for r in sample if r["outcome"]["resolved"])
        )
    total = sum(r["outcome"]["r"] for r in take if r["outcome"]["resolved"])
    return {
        "schema": VERSION,
        "decisions": dict(
            Counter((r["choice"] or {}).get("decision", "uncommitted") for r in rows)
        ),
        "take_all": summary(rows),
        "jo_take": summary(take),
        "fixed_context_filter": summary(baseline),
        "matched_count_random": {
            "mean_total_r": sum(totals) / 1000,
            "descriptive_percentile": sum(v <= total for v in totals) / 1000
            if take
            else None,
        },
        "warning": "Discovery development; five correlated sessions; no significance or options-performance claim",
        "delayed_entry": "not modeled; imported factory outcomes only",
    }
