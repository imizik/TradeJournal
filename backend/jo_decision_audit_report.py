"""Standalone, network-free HTML view of the offline decision audit."""

from html import escape


def e(value):
    return escape(str(value), quote=True)


def number(value):
    return "Unknown" if value is None else f"{value:,.3f}".rstrip("0").rstrip(".")


def table(headers, rows):
    return '<div class="scroll" tabindex="0"><table><thead><tr>' + ''.join(f'<th>{e(h)}</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{e(v)}</td>' for v in row) + '</tr>' for row in rows) + '</tbody></table></div>'


def render(report):
    facts = report["kind"] == "facts"
    title = "Jo · Decision evidence" if facts else "Jo · Selection comparison"
    subtitle = "What the saved reasons got right, wrong, or left unverified." if facts else "What changed on the same completed cards, and what remains unknown."
    parts = []
    if facts:
        counts = report["claims"]
        parts.append('<section class="metrics">' + ''.join(f'<div><strong>{e(counts.get(k, 0))}</strong><span>{e(label)}</span></div>' for k, label in (("mismatch", "Factual mismatches"), ("match", "Literal matches"))) + f'<div><strong>{sum(v for k,v in counts.items() if k not in ("match", "mismatch"))}</strong><span>Unverified checks</span></div></section>')
        parts.append(f'<p class="notice">{e(report["scope"])} Matches are checks of quoted facts, not a grade for Jo.</p>')
        parts.append('<h2>Runs and coverage</h2>' + table(["Prompt", "Run status", "Saved decisions", "Median / p95 seconds"], [(r["prompt_version"], r["status"], r["saved_decisions"], f'{number(r["timing"]["median_seconds"])} / {number(r["timing"]["p95_seconds"])}') for r in report["runs"]]))
        parts.append('<h2>Saved decisions</h2><p>Factual mismatches appear first. Expand a decision to inspect its original reason and each literal check. Use your browser’s Find to locate a symbol or card.</p>')
        if not report["rows"]:
            parts.append('<p class="notice">No saved decisions in this export. Nothing has been scored or inferred.</p>')
        for row in sorted(report["rows"], key=lambda r: (-r["mismatches"], r["cutoff"], r["source_card_id"])):
            label = f'{row["symbol"]} · {row["decision"].upper()} · {row["mismatches"]} mismatches'
            matched = sum(c["status"] == "match" for c in row["checks"])
            unverified = len(row["checks"]) - matched - row["mismatches"]
            parts.append(f'<details><summary>{e(label)}<small>{matched} matched · {unverified} unverified<br>{e(row["cutoff"])} · {e(row["prompt_version"])}</small></summary><p class="reason">{e(row["reason"])}</p>')
            parts.append(table(["Claim", "Quoted", "Frozen fact (rounded)", "Result"], [(c["field"], ", ".join(c["quoted"]) or "—", format(c["expected"], ".8g") if type(c["expected"]) in (int, float) else c["expected"] if c["expected"] is not None else "Unavailable", c["status"]) for c in row["checks"]]))
            parts.extend(f'<p class="notice">{e(w)}</p>' for w in row["warnings"])
            parts.append(f'<p class="muted">Card {e(row["source_card_id"])} · opportunity {e(row["opportunity_id"])}<br>Evidence SHA256 {e(row["evidence_sha256"])}<br>Receipt SHA256 {e(row["receipt_sha256"])}</p></details>')
        parts.append('<h2>Pairs worth reviewing</h2><p>These share symbol, setup family, direction and context category. Different times and other conditions can justify different choices; they are not inconsistency findings.</p>')
        parts.append(table(["Group", "Take opportunity", "Skip opportunity"], [(" / ".join(map(str, p["group"])), p["take"], p["skip"]) for p in report["contrasts"]]) if report["contrasts"] else '<p>No take/skip contrast pairs in this export.</p>')
    else:
        parts.append(f'<p class="notice">Already-revealed export · control: {e(report["control"])} · {e(report["revealed_at"])}. Descriptive underlying R only.</p>')
        parts.append('<h2>Selections on identical cards</h2>' + table(["Arm", "Takes / available", "Unresolved takes", "Total R", "Change vs control"], [(name, f'{a["selected"]} / {a["available"]}', a["unresolved"], number(a["total_r"]), number(a["delta_r"])) for name, a in report["arms"].items()]))
        parts.append('<p>A paired difference cancels unchanged selections; it can be known even when a shared selected outcome is unresolved. It is unknown if a changed selection is unresolved.</p>')
        parts.append('<h2>Reference selections</h2>' + table(["Reference", "Selected", "Unresolved", "Total R"], [(label, report[key]["selected"], report[key]["unresolved"], number(report[key]["total_r"])) for key,label in (("take_all", "Take every card"), ("fixed_filter", "day_move ≥ 0 and trend ≥ 0"))]))
        for name, arm in report["arms"].items():
            parts.append(f'<details><summary>{e(name)} · session breakdown</summary>' + table(["Session", "Takes", "Unresolved", "Total R", "Change vs control"], [(d["session"], d["selected"], d["unresolved"], number(d["total_r"]), number(d["delta_r"])) for d in arm["by_session"]]) + f'<p>Prompt SHA256 {e(arm["assignment"]["prompt_sha256"])}</p></details>')
        parts.append('<h2>Changed selections</h2><p>Realized results describe this sample. A losing choice is not automatically a reasoning error.</p>')
        if not report["changes"]:
            parts.append('<p class="notice">All arms selected the same cards.</p>')
        for row in report["changes"]:
            parts.append(f'<details><summary>{e(row["arm"])} · {e(row["symbol"])} · {e(row["change"])} · {number(row["outcome"]["r"])} R<small>{e(row["cutoff"])}</small></summary><h3>Control · {e(row["control_decision"])}</h3><p class="reason">{e(row["control_reason"])}</p><h3>Comparison · {e(row["decision"])}</h3><p class="reason">{e(row["reason"])}</p><p>Card {e(row["source_card_id"])}</p></details>')
    parts.append('<h2>How to read this</h2><ul>' + ''.join(f'<li>{e(x)}</li>' for x in report["limits"]) + '<li>Elapsed timings include interruptions and tool latency, not live execution latency.</li></ul>')
    parts.append(f'<footer>{e(report["format"])} · source SHA256 {e(report["source_sha256"])}</footer>')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>{e(title)}</title><style>
:root{{color-scheme:dark;font:16px/1.6 system-ui,sans-serif;background:hsl(222 20% 9%);color:hsl(210 20% 90%)}}*{{box-sizing:border-box}}body{{margin:0}}main{{max-width:1100px;margin:auto;padding:40px 24px 70px}}h1{{font-size:clamp(1.8rem,5vw,2.8rem);line-height:1.2;margin:0 0 12px}}h2{{margin-top:36px;font-size:1.25rem}}h3{{font-size:1rem}}p,li,footer,td{{overflow-wrap:anywhere}}.subtitle,.muted,footer,small{{color:hsl(215 16% 68%)}}.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:30px 0}}.metrics div,details,.notice{{background:hsl(222 20% 12%);border:1px solid hsl(222 20% 23%);border-radius:12px;padding:18px}}.metrics strong{{display:block;font-size:2rem;line-height:1.2}}.metrics span{{font-size:.85rem}}details{{margin:12px 0}}summary{{cursor:pointer;font-weight:650}}summary:focus-visible,.scroll:focus-visible{{outline:2px solid #92bce8;outline-offset:5px}}small{{display:block;font-size:.8rem;font-weight:400;margin-top:4px}}.reason{{white-space:pre-wrap;border-left:3px solid #92bce8;padding-left:14px}}.scroll{{overflow-x:auto;max-width:100%;border:1px solid hsl(222 20% 23%);border-radius:8px}}table{{border-collapse:collapse;width:100%;min-width:520px;font-size:.88rem}}th,td{{min-width:110px;text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid hsl(222 20% 23%)}}th{{color:#b4cbe4}}footer{{font-size:.75rem;margin-top:40px}}.muted{{font-size:.75rem}}@media(max-width:500px){{main{{padding:26px 16px 48px}}.metrics{{gap:6px}}.metrics div{{padding:12px 8px}}.metrics strong{{font-size:1.7rem}}.metrics span{{font-size:.75rem}}details{{padding:14px}}}}
</style></head><body><main><h1>{e(title)}</h1><p class="subtitle">{e(subtitle)}</p>{''.join(parts)}</main></body></html>'''
