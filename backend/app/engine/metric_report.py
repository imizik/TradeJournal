"""Offline, self-contained review pages over validation evidence."""
from html import escape

from app.engine.metric_reference import ET, timestamp


def cell(value):
    return escape("—" if value is None else str(value))


def table(headers, rows):
    return "<table><thead><tr>" + "".join(f"<th>{cell(h)}</th>" for h in headers) + "</tr></thead><tbody>" + "".join(
        "<tr>" + "".join(f"<td>{cell(v)}</td>" for v in row) + "</tr>" for row in rows) + "</tbody></table>"


def chart(samples, fields, label):
    """Plot only observed points; do not interpolate across missing minutes."""
    if not samples:
        return "<p>No cached holding-minute evidence available.</p>"
    times = [timestamp(s["timestamp"]).timestamp() for s in samples]
    values = [s[field] for s in samples for field in fields]
    low, high = min(0, min(values)), max(values)
    if fields == ("high", "low"):
        padding = (max(values) - min(values)) * 0.05 or 0.01
        low, high = min(values) - padding, max(values) + padding
    span = high - low or 1
    def x(t):
        return 65 + (t - times[0]) / (times[-1] - times[0] or 1) * 875

    def y(v):
        return 180 - (v - low) / span * 145
    colors = ("#087e8b", "#ad3453", "#8056aa")
    parts = [f'<svg role="img" aria-label="{cell(label)}" viewBox="0 0 1000 215">',
             f'<text x="65" y="18">{cell(label)}</text>',
             f'<text x="0" y="40">{high:.2f}</text><text x="0" y="180">{low:.2f}</text>',
             f'<path d="M65 {y(low):.2f}H940" stroke="#ccc"/>']
    for index, field in enumerate(fields):
        for time, sample in zip(times, samples):
            point = sample[field]
            parts.append(f'<circle cx="{x(time):.2f}" cy="{y(point):.2f}" r="2" fill="{colors[index]}">'
                         f'<title>{cell(sample["timestamp"])} {cell(field)}={point:.6f}</title></circle>')
    for time, px in ((samples[0]["timestamp"], 65), (samples[-1]["timestamp"], 780)):
        parts.append(f'<text x="{px}" y="206">{cell(timestamp(time).astimezone(ET).strftime("%m-%d %H:%M ET"))}</text>')
    parts.append('</svg><p>' + " · ".join(f'<span style="color:{colors[i]}">{cell(f)}</span>' for i, f in enumerate(fields)) + '</p>')
    return "".join(parts)


def html_report(report):
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><title>Trade metric evidence</title>',
             '<style>body{font:15px system-ui;max-width:1100px;margin:40px auto;padding:0 20px;color:#18232b}'
             'table{border-collapse:collapse;width:100%;font-size:12px;margin:12px 0}td,th{border:1px solid #ddd;'
             'padding:6px;text-align:left;overflow-wrap:anywhere}svg{width:100%;background:#f8fafb}'
             'svg text{font:12px system-ui}article{border-top:2px solid #ccc;padding:20px 0}summary{cursor:pointer}'
             'p{line-height:1.5}nav a{margin-right:12px;display:inline-block;line-height:2}</style><body><h1>Trade metric evidence</h1>',
             f'<p>Snapshot {cell(report.get("snapshot_at"))} · feed {cell(report["feed"])} · {cell(report["reference_revision"])}</p>',
             '<p><strong>Broker verification has not been performed.</strong> This compares internal calculations using supplied fills and cached bars. '
             'Minute extremes are estimates; option-cache feed provenance is unknown. Revised historical bars cannot prove live availability.</p>',
             table(["Status", "Checks"], [(s, report["counts"].get(s, 0)) for s in ("matched", "mismatch", "stale", "unavailable", "error")]),
             '<p>The 30-case default sample targets diverse hard cases. It is not a statistical accuracy estimate. '
             'Points show observed minutes only; gaps are not interpolated. Hover points for raw evidence. Prices and P&amp;L are in dollars.</p>',
             '<nav>' + " ".join(f'<a href="#{cell(s["trade_id"])}">{cell(s.get("ticker"))}</a>' for s in report["review_samples"]) + '</nav>']
    parts.append(f'<details><summary>{len(report["unlinked_fill_ids"])} unlinked fills need source reconciliation</summary>'
                 + table(["Fill ID"], [[f] for f in report["unlinked_fill_ids"]]) + '</details>')
    for sample in report["review_samples"]:
        parts.append(f'<article id="{cell(sample["trade_id"])}"><h2>{cell(sample.get("ticker"))} · {cell(sample["trade_id"])}</h2>')
        if sample.get("error"):
            parts.append(f'<p>{cell(sample["error"])}</p></article>')
            continue
        parts.append(f'<p>{cell(", ".join(sample["categories"]))}</p>')
        parts.append(table(["Executed ET", "Side", "Quantity", "Price", "Fill ID"],
                           [[f["executed_at"], f["side"], f["contracts"], f["price"], f["id"]] for f in sample["source_fills"]]))
        parts.append(table(["Independent accounting", "Value"], sample["accounting"].items()))
        for name in ("option", "underlying"):
            result = sample.get(name)
            if not result:
                continue
            parts.append(f'<h3>{name.title()} evidence</h3>')
            if result["reason"]:
                parts.append(f'<p>{cell(result["reason"])}</p>')
            else:
                points = result.get("samples", [])
                if name == "option":
                    parts.append(chart(points, ("total", "adverse", "realized"), "Observed total favorable, open adverse, realized P&L ($)"))
                    parts.append(chart(points, ("quantity",), "Remaining option quantity (contracts)"))
                    parts.append(f'<p>Peak endpoint: {cell(result.get("peak_minute"))}. Final realized P&amp;L is also considered; it may exceed all bar points.</p>')
                else:
                    parts.append(chart(points, ("high", "low"), "Underlying holding-minute high and low ($)"))
                parts.append(table(["Independent metric", "Value"], result["values"].items()))
        parts.append('<details><summary>All stored versus independent checks</summary>' + table(
            ["Field", "Fill ID", "Stored", "Reference", "Status", "Reason"],
            [[c["field"], c.get("fill_id"), c.get("stored"), c.get("reference"), c["status"], c.get("reason")] for c in sample["checks"]])
            + '</details><ul>' + "".join(f'<li>{cell(limit)}</li>' for limit in sample["limits"]) + '</ul></article>')
    parts.append('</body></html>')
    return "\n".join(parts)
