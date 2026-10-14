# Do macro release days trend? (October 14, 2026)

Research only. `macro.py` joins the `detect.py` day labels (157 SPY sessions,
March 2 – October 13, 2026) with release dates from the BLS news-release
archives (CPI, PPI, jobs) and the Fed's FOMC calendar. Full output: `out/macro.md`.
Samples are tiny (5–7 days per release type): treat these as leads, not results.

- **CPI and jobs mornings mostly chop.** 6 of 7 CPI days and 6 of 7 jobs days
  ended choppy; one of each trended down. A big reaction at 08:30 usually got
  faded (for example jobs −0.90 ATR gap on March 6, CPI +1.29 ATR on September 11:
  both choppy).
- **FOMC days leaned down:** 3 of 5 ended as trend-down days (all-session base rate 12%).
- **A gap down after an 08:30 release followed through more often than an ordinary
  gap down:** gap ≥ 0.3 ATR down trended down on 2 of 5 release days vs 2 of 29
  other days. Gap ups after releases did not (1 of 5 vs 8 of 43).
- **The intraday checks were somewhat better on release days** (down: afternoon
  new low 3 of 4, base 1 of 2, VIXY 1 of 1, SPY+QQQ+IWM 1 of 1), but each is one
  to four days.

Meaning: the macro calendar is a reason to watch more closely and to trust a
down-move a bit more once it holds, not a prediction at the open. A release
day plus a gap down that is not filled, plus the intraday evidence, is the
combination worth Jo's attention. Today (October 14, CPI) can be added to this
table after the session's bars are final.
