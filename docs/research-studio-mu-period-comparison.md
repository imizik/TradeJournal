# MU: comparison across market periods

Owner-selected exploratory comparison, computed October 11, 2026 from the existing local SIP minute cache. No provider fetch, order execution or Factory validation. Newer source dates read for this study remain exposed.

The rules are unchanged: MU, 10:00–11:30 ET; first completed five-minute decision each session with a 15-minute decline at most -0.25 prior daily ATR(14); cumulative relative volume at least 1.5× or 2×. Returns run from the immediate next complete five-minute open to the exact 30-minute close. Percentages are price returns, not trading P&L.

| Period | 1.5× endpoint N | 1.5× mean return | 1.5× versus ordinary baseline | 2× endpoint N | 2× mean return | 2× versus ordinary baseline |
|---|---:|---:|---:|---:|---:|---:|
| Original discovery | 25 | +0.101% | +0.126 pp | 14 | +0.082% | +0.107 pp |
| Late 2024 | 5 | +0.476% | +0.471 pp | 2 | +0.310% | +0.300 pp |
| 2025 | 21 | +0.002% | -0.010 pp | 11 | +0.183% | +0.181 pp |
| 2026 through October 9 | 10 | +0.146% | +0.133 pp | 2 | -0.705% | -0.731 pp |

## Uncertainty and interpretation

| Period | 1.5× baseline-adjusted 95% interval | 2× baseline-adjusted 95% interval | Within-period change from 1.5× to 2× |
|---|---|---|---|
| Original discovery | -0.233 to +0.536 pp | -0.425 to +0.664 pp | -0.333 to +0.334 pp |
| Late 2024 | Unavailable: fewer than 20 eligible weeks | Unavailable: fewer than 20 eligible weeks | Unavailable: fewer than 20 eligible weeks |
| 2025 | -0.544 to +0.584 pp | -0.348 to +1.104 pp | -0.312 to +0.892 pp |
| 2026 through October 9 | -1.102 to +1.313 pp | Unavailable: only 1709 / 2,000 valid draws (needs 1,900) | Unavailable: only 1709 / 2,000 valid draws (needs 1,900) |

Every available interval includes zero. The late-2024 window has only 14 eligible weeks, so its intervals are unavailable. The 2026 2× condition selects only two events: 291 zero-event paired draws leave 1,709 valid draws, below the frozen 1,900-draw requirement. Its negative average is an observation, not a reliable estimate of future performance.

The direction and magnitude vary by period. This is reason to check recent relevance, not proof of a structural regime shift, a political/PDT cause, or an executable edge. We did not tune thresholds after viewing newer outcomes. No across-year paired test is claimed.

## Coverage and reproducibility

Newer MU coverage is complete for all 64 late-2024, 250 2025 and 194 2026 scheduled sessions, with zero missing scheduled minutes, duplicate minutes, invalid rows or missing session files. The ordinary eligible populations are 1,216, 4,750 and 3,686 moments respectively. Original discovery reproduces the prior trial: 25 versus 14 events and +0.101% versus +0.082% mean returns. The current source/code identities generate new research run IDs; old saved results are preserved.

SIP directory/current raw writer provenance has no supplier receipt. Price basis retains Factory-inferred splits within each cutoff and excludes dividends. Calendar/source protocol and conservative quality masks are specified in the [fixed MU contract](agent/research-studio-newer-mu.md).

| Period | 1.5× run ID | 2× run ID |
|---|---|---|
| Original discovery | `bccdd53b0fb27dc45b5fb440163d09acb57f83d6c85b5dd9351ca36f240d2433` | `5e1a2b7d6d96a1576e00b3ecb913c9d855a380a853cbca9e1896fdf3f2a096e7` |
| Late 2024 | `a7afed633312bb842f722c318078b66dd9feb18608fd40c42fb2b729d9d414dd` | `9d4e352dfcb47255fbda6db994577b3741a3657b6bc8c95640efc194e8ab7bc1` |
| 2025 | `8cc8fb11c921d1f1222bf8bed47164d830aad7c39b26c0184873bb71b4b2b732` | `48094fddfde835aaa65215873bcba3bdc24187e38b1e66e96f04fc73aa98dde3` |
| 2026 through October 9 | `63ab71776a536e8ee0ab1f94a7181fc008f465b1cdf261b67ced17a0387608d8` | `ca9183932ebcc03f2cb1a71913c51df1a28069c600aba99f66cb566ca77548d0` |

The private local study store and full receipts are at `/tmp/research-studio-newer/mu-study-store` and `/tmp/research-studio-newer/mu-summary.json`; they are not committed. App support is delivered separately through the reviewed branch. Cache transfer or passing tests alone does not activate the newer-data app mode.
