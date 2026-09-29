"""The strategy factory's weekly brief: the catalog, the ledger digest, the
discovery evidence, the review of the idea model's answer, and the report."""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from app.engine.factory_brief import (
    SYSTEM_PROMPT,
    Proposal,
    brief,
    catalog,
    evidence,
    ledger_digest,
    lessons_from,
    review,
    spec_changes,
    spec_file,
    weekly_report,
)
from app.engine.factory_data import FEATURES
from app.engine.factory_rules import FAMILIES, Trade, canonical, from_canonical, parse_spec, spec_id
from app.engine.market_map import ET

DEFAULT_SWING = spec_id(parse_spec({"family": "recovery_swing"}))


def idea(title: str, spec: dict | str, **extra) -> dict:
    return {"title": title, "hypothesis": f"{title} should work because of a reason.", "builds_on": extra.get("builds_on", ""),
            "change": extra.get("change", "one change"), "from_evidence": extra.get("from_evidence", False),
            "spec_json": spec if isinstance(spec, str) else json.dumps(spec)}


def test_the_catalog_lists_every_family_with_its_settings_and_defaults():
    families = catalog()["families"]
    assert set(families) == set(FAMILIES)
    swing = families["recovery_swing"]
    assert swing["settings"]["stop_bars"] == 4 and swing["sides"] == ["long"]
    assert swing["defaults"]["timeframe"] == 15 and "NBIS recovery swing" in swing["about"]
    assert families["vwap_reclaim"]["defaults"]["window"] == [935, 1500]
    assert catalog()["features"] == FEATURES


def test_spec_changes_are_what_differs_from_the_family_defaults():
    assert spec_changes(canonical(parse_spec({"family": "vwap_reclaim"}))) == {}
    changed = parse_spec({"family": "vwap_reclaim", "params": {"confirm_bars": 2}, "window": [1000, 1500],
                          "filters": [{"feature": "rvol", "min": 1.5}]})
    shown = spec_changes(canonical(changed))
    assert shown == {
        "params": {"confirm_bars": 2},
        "window": [1000, 1500],  # back in HHMM and min/max, the way a spec is written
        "filters": [{"feature": "rvol", "min": 1.5}],
    }
    # What the model sees can be copied into a new spec as it is.
    assert spec_id(parse_spec({"family": "vwap_reclaim", **shown})) == spec_id(changed)


def test_a_spec_rebuilds_exactly_from_its_ledger_form():
    spec = parse_spec({"family": "failed_breakout", "window": [1000, 1400], "exits": {"target_r": 2.0},
                       "filters": [{"feature": "trend", "max": 0}], "model": {"kind": "logistic", "features": ["gap"]}})
    rebuilt = from_canonical(json.loads(json.dumps(canonical(spec))), "named")
    assert spec_id(rebuilt) == spec_id(spec) and rebuilt.name == "named" and rebuilt.window == (600, 840)


def test_the_ledger_digest_keeps_hand_research_and_hides_exam_numbers():
    records = [
        {"id": DEFAULT_SWING, "name": "by hand", "source": "hand research", "verdict": "failed_confirmation",
         "summary": "worked in 2024-25 only"},
        {"id": DEFAULT_SWING, "name": "the factory's run", "source": "factory", "verdict": "failed_exam",
         "spec": canonical(parse_spec({"family": "recovery_swing"})), "notes": "why",
         "periods": {"discovery": {"n": 500, "mean_r": 0.1, "edge": 0.2, "edge_t": 2.5, "tickers": 10, "tickers_up": 7},
                     "holdout": {"n": 90, "mean_r": -0.777, "edge": -0.5, "edge_t": -1.0}}},
    ]
    (item,) = ledger_digest(records)
    assert item["name"] == "the factory's run" and item["by_hand_before"] == "worked in 2024-25 only"
    assert item["results"]["discovery"]["t"] == 2.5 and item["results"]["discovery"]["tickers_up"] == "7/10"
    assert "holdout" not in item["results"] and item["exam"] == "failed"
    assert "0.777" not in json.dumps(ledger_digest(records))


def closed_trade(k: int, r: float, side: int = 1, minute: int = 600, reason: str = "stop") -> Trade:
    moment = datetime(2024, 3, 4, minute // 60, minute % 60, tzinfo=ET)
    t = Trade("X", side, 0, moment, 1, moment, 100.0, 100.0 - side, None, exit_reason=reason)
    t.exit_price = 100.0 + side * r
    t.features = {"rvol": float(k), "trend": float("nan")}
    return t


def test_evidence_splits_trades_by_side_time_exit_and_feature_fifths():
    trades = [closed_trade(k, 1.0 if k >= 25 else -1.0, minute=600 if k % 2 else 900,
                           reason="target" if k >= 25 else "stop") for k in range(50)]
    e = evidence(trades)
    assert e["all"] == {"trades": 50, "avg_r": 0.0, "win_pct": 50.0}
    assert e["by_side"]["long"]["trades"] == 50 and set(e["by_signal_time"]) == {"09:30-10:30", "14:00-16:00"}
    assert e["by_exit"]["target"]["avg_r"] == 1.0 and e["by_exit"]["stop"]["avg_r"] == -1.0
    fifths = e["by_feature_fifth"]["rvol"]
    assert [row["avg_r"] for row in fifths] == [-1.0, -1.0, -0.0, 1.0, 1.0]
    assert (fifths[0]["from"], fifths[0]["to"], fifths[-1]["to"]) == (0.0, 9.0, 49.0)
    assert "trend" not in e["by_feature_fifth"]  # all missing


def test_review_accepts_a_good_idea_and_refuses_the_rest():
    good = {"family": "vwap_reclaim", "timeframe": 5, "exits": {"target_r": 2.0, "max_minutes": 60}}
    answer = {"ideas": [
        idea("Five-minute reclaim", good, builds_on="vw-3d24a7243d", change="five-minute bars"),
        idea("Picky", {"family": "vwap_reclaim", "tickers": ["NBIS", "MU"]}),
        idea("Cheap", {"family": "vwap_reclaim", "costs": {"slippage_bps": 0.5}}),
        idea("Odd costs", {"family": "vwap_reclaim", "costs": {"commission": 0}}),
        idea("Stacked", {"family": "vwap_reclaim", "filters": [{"feature": f, "min": 0} for f in ("trend", "gap", "rvol")]}),
        idea("Broken", "{not json"),
        idea("Unknown", {"family": "orb"}),
        idea("Old", {"family": "recovery_swing"}),
        idea("Again", good),
        idea("Learned", {"family": "failed_breakout", "timeframe": 5, "model": {"kind": "logistic"}}),
        idea("", {"family": "failed_breakout", "timeframe": 30}),
    ], "lessons": "", "wanted": []}
    proposals = review(answer, {DEFAULT_SWING}, budget=2)
    problems = {p.title: p.problem for p in proposals}
    assert problems == {
        "Five-minute reclaim": "",
        "Picky": "it picks its own tickers",
        "Cheap": "it changes the costs",
        "Odd costs": "it changes the costs",
        "Stacked": "it has more than 2 filters",
        "Broken": "its spec is not valid JSON",
        "Unknown": problems["Unknown"],
        "Old": "the same rules are already in the ledger",
        "Again": "it repeats another idea this week",
        "Learned": "it does not fit this week's budget",  # its rules are new too: two candidates, one left
        "": "it has no title or no hypothesis",
    }
    assert problems["Unknown"].startswith("its spec is invalid: family must be one of")
    accepted = proposals[0]
    assert accepted.runs == 1 and accepted.spec.name == "Five-minute reclaim"
    assert accepted.spec.notes == ("Five-minute reclaim should work because of a reason. "
                                   "Builds on vw-3d24a7243d: five-minute bars")
    learned = review({"ideas": [answer["ideas"][9]]}, set(), budget=3)[0]
    assert learned.runs == 2 and learned.problem == ""
    malformed = review({"ideas": [idea("Null filter", {"family": "vwap_reclaim", "filters": [None]}),
                                  idea("Number filters", {"family": "vwap_reclaim", "filters": 5}),
                                  idea("A list", "[1, 2]")]}, set(), 3)
    assert [p.problem for p in malformed] == ["its spec is invalid: a filter must be a JSON object",
                                              "its spec is invalid: filters must be a list",
                                              "its spec is not a JSON object"]


def test_a_saved_spec_parses_back_to_the_same_rules():
    (p,) = review({"ideas": [idea("Windowed", {"family": "failed_breakout", "window": [1000, 1400]},
                                  from_evidence=True)]}, set(), 3)
    name, data = spec_file(p)
    assert name == "windowed.json" and data["window"] == [1000, 1400]
    assert spec_id(parse_spec(data)) == p.id
    assert data["notes"].endswith("Drawn from the discovery evidence, so the screen is not an independent test of it.")


def ledger_line(identifier: str, name: str, verdict: str, t: float, confirm: bool = False) -> dict:
    periods = {"discovery": {"n": 1200, "mean_r": 0.021, "edge": 0.04, "edge_t": t}}
    if confirm:
        periods["confirm"] = {"n": 800, "mean_r": 0.05, "edge": 0.09, "edge_t": 1.7}
    screened = verdict != "failed_screen"
    gates = {"screen": {"passed": screened, "checks": [["beats random entries, t = 0.90 (at least 2.00)", screened]]}}
    return {"id": identifier, "name": name, "verdict": verdict, "periods": periods, "gates": gates,
            "reached_confirmation": confirm}


def test_the_weekly_report_and_its_summary():
    answer = {"ideas": [idea("Wide swing", {"family": "recovery_swing", "exits": {"target_r": 3.0}}),
                        idea("Cheap", {"family": "recovery_swing", "costs": {"slippage_bps": 0}}),
                        idea("Filtered", {"family": "recovery_swing", "filters": [{"feature": "minutes", "min": 30}]})],
              "lessons": "Nothing works after costs yet.", "wanted": ["an opening-range family", " "]}
    proposals = review(answer, set(), 3)
    wide, _, filtered = proposals
    records = {wide.id: ledger_line(wide.id, "Wide swing", "failed_screen", 0.9),
               filtered.id: ledger_line(filtered.id, "Filtered", "failed_confirmation", 2.4, confirm=True)}
    markdown, summary = weekly_report(date(2026, 10, 4), proposals, records, answer, "The bar is 2.64.", "footer text")
    assert markdown.startswith("# Strategy factory, week of 2026-10-04\n\n**2 ideas judged, none passed "
                               "(1 reached confirmation).** The bar is 2.64.")
    assert "| Wide swing | failed the screen | 1,200 trades, +0.021R a trade, +0.040R vs random (t 0.90) | — |" in markdown
    assert "| Filtered | failed confirmation |" in markdown and "800 trades" in markdown
    assert "- Screen failed on: beats random entries, t = 0.90 (at least 2.00)." in markdown
    assert "## Refused proposals\n\n- Cheap: it changes the costs." in markdown
    assert "## What the ledger says now\n\nNothing works after costs yet." in markdown
    assert "- an opening-range family" in markdown and markdown.rstrip().endswith("footer text")
    assert summary == ("2 ideas judged, none passed (1 reached confirmation). "
                       "Closest: Filtered (failed confirmation). The bar is 2.64.")
    assert lessons_from(markdown) == "Nothing works after costs yet."
    records[filtered.id]["verdict"] = "passed"
    _, passed = weekly_report(date(2026, 10, 4), proposals, records, answer, "", "")
    assert passed.startswith("1 of 2 ideas passed confirmation: Filtered.")
    empty, quiet = weekly_report(date(2026, 10, 4), [proposals[1]], {}, answer, "", "")
    assert quiet.startswith("No idea was accepted this week") and "## Refused proposals" in empty


def test_the_brief_holds_the_rules_the_catalog_the_ledger_and_the_evidence():
    records = [{"id": "hand-x", "name": "an old idea", "source": "hand research", "verdict": "failed_confirmation",
                "summary": "it lost"}]
    text = brief(date(2026, 10, 4), records, {"recovery_swing": {"all": {"trades": 3}}}, [("2026-09-27", "be careful")],
                 budget=2, bar_t=2.64, candidates=11)
    assert text.startswith("Today is 2026-10-04. Propose up to 2 new candidates this week.")
    assert "t >= 2.64: 11 candidates" in text and '"hand-x"' in text and '"trades": 3' in text
    assert "## Your lessons from earlier weeks\n2026-09-27: be careful" in text
    assert '"reclaim_level": "ema"' in text  # the catalog's settings
    assert "Trade the core universe and the default costs" in SYSTEM_PROMPT


def test_a_proposal_without_a_spec_has_no_id():
    assert Proposal("t", "h", "", "", False).id == ""
    with pytest.raises(AssertionError):
        spec_file(Proposal("t", "h", "", "", False))
