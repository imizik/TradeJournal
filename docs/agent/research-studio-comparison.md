# Research Studio: event evidence and period comparison

The owner selected this extension after inspecting the 2026 MU events. The
goal is to make that review possible inside the app, using existing frozen
results and their recorded outcome exposures.

After an explicit analysis reveal, every event shows its exact 15/30/60-minute
and scheduled-close return. Units follow the analysis selector: percentage of
next open or prior daily ATR(14). Missing endpoints retain their reason rather
than becoming zero. Selecting a row inspects that result's exact snapshot,
including when the row belongs to the other period.

The selected horizon's valid endpoints supply the median, strictly positive
count/share, sample standard deviation, and two single-event omission means.
Zero remains in the denominator. With no valid values the metrics are
unavailable; dispersion and omission means require at least two. Omissions
are descriptive sensitivity checks: they do not filter the population or
recompute a baseline, interval or trading strategy.

Period comparison offers completed saved runs with identical predicates,
universe and decision window in non-overlapping periods. Loading a comparison
records another aggregate exposure through the existing result command.
Actual returned run identity, definitions, calculation fingerprint and
specification are checked before showing the second period. Mismatched
calculation versions require rerunning the studies on the same release.
Selecting another run clears the previous comparison immediately, and a
delayed superseded result cannot replace the new selection.

Each card keeps its own period, endpoint N, mean, median, positive share,
dispersion, ordinary baseline, difference, volatility-normalized mean and
baseline-adjusted interval. There is no pooled population or paired
cross-period interval. The [fixed newer MU protocol](research-studio-newer-mu.md)
and Factory validation remain unchanged.

Verification uses hand-computed endpoint metrics and a browser journey from
original discovery to 2026, explicit reveals/comparison exposure, unit changes,
other-period chart identity, delayed-response refusal and desktop/390px phone
layout. Browser prices are invented fixtures, not evidence of a trading edge.
