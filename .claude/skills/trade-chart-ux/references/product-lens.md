# Product lens (every page that is not a chart)

Start from the job, not the page's looks. Routes and their files are in
`docs/agent/feature-map.md` (The screens).

| Page | The job to test |
|---|---|
| `/` Today | What needs attention now, how fresh is it, what do I do next? |
| `/analytics` | What am I doing well or badly, and is the sample big enough to believe? Filters, summary → trade drill-down, period and account scope. |
| `/trades`, `/fills` | Find, understand and correct one execution: search, sort, timezone, shares vs contracts, edit safeguards. |
| `/daily` | Review a day: what closed, P&L, what I noted, quick move to the next day. |
| `/signals` | What fired, from which source, how old, what was concluded. Observed vs inferred. |
| `/strategy-lab`, `/research` | Can a hypothesis be run and judged honestly, and found again later? |
| `/accounts` | Scope, dates and integrity of what I see. Never change connections in an audit. |

## Review grid (only what applies)

1. **Hierarchy:** one primary question per screen; not a wall of equal tiles.
2. **Disclosure:** frequent analysis visible; rare detail one click away.
   Hidden status, errors or stale data is a defect, not a simplification.
3. **Numbers:** aligned, tabular figures; stable precision, units, signs and
   periods; absent is not zero; estimated is not observed.
4. **Clarity:** specific action labels; state what is filtered, what changed,
   what is pending.
5. **Continuity:** filters, sort, selection and scroll survive back
   navigation and deep links.
6. **States:** loading, empty, partial failure, error, long names, large
   tables — each distinct and actionable.
7. **Responsive:** desktop and 390px phone; nothing clipped or unreachable;
   touch targets about 44px where the phone uses them.
8. **Consistency:** reuse the existing colors (`frontend/app/globals.css`),
   components, verbs and drawer/sheet/modal patterns. If a page legitimately
   differs, say why instead of homogenizing.
9. **Speed felt:** sort/filter/navigation acknowledge immediately; no
   blanking; separate server wait from render work.

On financial pages, units, denominators, sample size, period and freshness
matter more than minimalism. Be suspicious of "clean modern" proposals and
card consolidation.

When the user approves a cross-page convention, record it in the document
that owns that area (for charts, `docs/charts-roadmap.md`) rather than
starting a separate design document.
