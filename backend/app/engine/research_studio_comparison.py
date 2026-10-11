"""R4 paired descriptive comparisons; R1/R2 event and outcome semantics stay fixed."""
from datetime import timedelta
import math

import numpy as np

from app.engine.market_map import ET

from app.engine.research_studio_analysis import (
    HORIZONS, UNITS, SPEC, _check, _estimate, outcome,
)


def event_id(row):
    return row["symbol"] + ":" + row["decision_time"]


def compare(observations, definitions, results, *, cancel=lambda: False):
    _check(cancel)
    parent, variant = results
    ids = [{event_id(e) for e in r["population"]["events"]} for r in results]
    for definition, result, expected in zip(definitions, results, ids):
        preview = observations.preview(definition)
        if preview["data_id"] != result["population"]["data_id"] or {
                event_id(e) for e in preview["events"]} != expected:
            raise ValueError("saved population differs from frozen comparison data")
    retained, removed, added = ids[0] & ids[1], ids[0] - ids[1], ids[1] - ids[0]
    saved = [{event_id(e): e for e in r["events"]} for r in results]
    if any(saved[0][key] != saved[1][key] for key in retained):
        raise ValueError("retained occurrences have different saved outcomes")
    # Small sets of eligible weeks/groups, then streaming sufficient totals.
    # No retained dictionary/list of every ordinary outcome row.
    metadata = []
    for definition in definitions:
        weeks, groups = set(), set()
        for moment in observations.eligible_moments(definition):
            local = moment.close.astimezone(ET)
            weeks.add(str(local.date() - timedelta(days=local.weekday())))
            groups.add((moment.symbol, local.hour*60 + local.minute))
        metadata.append((weeks, groups))
    weeks = sorted(metadata[0][0] | metadata[1][0])
    groups = sorted(metadata[0][1] | metadata[1][1])
    wi, gi = {w: i for i, w in enumerate(weeks)}, {g: i for i, g in enumerate(groups)}
    populations = []
    for definition, event_ids in zip(definitions, ids):
        totals = [[tuple(np.zeros((len(weeks), len(groups))) for _ in range(4))
                   for _ in UNITS] for _ in HORIZONS]
        for index, moment in enumerate(observations.eligible_moments(definition)):
            if index % 128 == 0:
                _check(cancel)
            row = outcome(observations, moment.symbol, moment.close)
            w, g = wi[row["week"]], gi[(row["symbol"], row["clock"])]
            selected = event_id(row) in event_ids
            for hi, horizon in enumerate(HORIZONS):
                for ui, unit in enumerate(UNITS):
                    value = row["outcomes"][horizon][unit]
                    if value is None:
                        continue
                    en, es, cn, cs = totals[hi][ui]
                    cn[w, g] += 1
                    cs[w, g] += value
                    if selected:
                        en[w, g] += 1
                        es[w, g] += value
        populations.append(totals)
    rng = np.random.Generator(np.random.PCG64(SPEC["seed"]))
    weights = np.zeros((SPEC["draws"], len(weeks)))
    if weeks:
        for k, draw in enumerate(rng.integers(0, len(weeks), (SPEC["draws"], len(weeks)))):
            weights[k] = np.bincount(draw, minlength=len(weeks))
    summaries = {}
    names = ("event_mean", "baseline_mean", "difference")
    for hi, horizon in enumerate(HORIZONS):
        summaries[horizon] = {}
        for ui, unit in enumerate(UNITS):
            _check(cancel)
            matrices, points = [], []
            for population, result in zip(populations, results):
                en, es, cn, cs = population[hi][ui]
                matrices.append((en, es, cn, cs))
                original = result["horizons"][horizon][unit]
                if int(en.sum()) != original["event_n"] or int(cn.sum()) != original["ordinary_n"]:
                    raise ValueError("saved sample counts differ from comparison engine")
                point = _estimate(*[a.sum(axis=0) for a in matrices[-1]])
                for name, value in zip(names, point):
                    original = result["horizons"][horizon][unit][name]
                    if (value is None) != (original is None) or value is not None and not math.isclose(
                            value, original, rel_tol=1e-12, abs_tol=1e-12):
                        raise ValueError("saved estimates differ from comparison engine")
                points.append(point)
            own_weeks = [len(meta[0]) for meta in metadata]
            enough = all(n >= SPEC["minimum_weeks"] for n in own_weeks)
            draws, invalid = [], 0
            if enough:
                for start in range(0, SPEC["draws"], 64):
                    _check(cancel)
                    pair = [[weights[start:start+64] @ a for a in arrays] for arrays in matrices]
                    for p, v in zip(zip(*pair[0]), zip(*pair[1])):
                        estimates = (_estimate(*p), _estimate(*v))
                        if any(x is None for estimate in estimates for x in estimate):
                            invalid += 1
                        else:
                            draws.append([v-p for p, v in zip(*estimates)])
            available = enough and len(draws) >= SPEC["minimum_valid_draws"]
            change = {name: v-p if p is not None and v is not None else None
                      for name, p, v in zip(names, *points)}
            change["uncertainty"] = {
                "intervals": {name: np.quantile(np.array(draws)[:, i], [.025, .975],
                                               method="linear").tolist() if available else None
                              for i, name in enumerate(names)},
                "eligible_weeks": len(weeks), "parent_weeks": own_weeks[0], "variant_weeks": own_weeks[1],
                "valid_draws": len(draws), "invalid_draws": invalid,
                "unavailable_reason": None if available else
                    "insufficient_weeks" if not enough else "insufficient_valid_draws",
            }
            summaries[horizon][unit] = {
                "parent": parent["horizons"][horizon][unit],
                "variant": variant["horizons"][horizon][unit], "change": change,
            }
    return {
        "parent_run_id": parent["run_id"], "variant_run_id": variant["run_id"],
        "data_id": observations.snapshot.identity,
        "sets": {"retained": sorted(retained), "removed": sorted(removed), "added": sorted(added)},
        "retained_outcomes_identical": True, "horizons": summaries,
        "method": {**SPEC, "version": "research-comparison-v1",
                   "direction": "variant minus parent",
                   "draws_shared": "same joint calendar-week multiplicities for both full populations",
                   "week_universe": "union of both eligible populations; each needs minimum eligible weeks"},
        "interpretation": "Descriptive, outcome-informed comparison; not independent validation.",
    }
