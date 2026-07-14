# Strategy Lab Pine Export Metadata

Strategy Lab can preserve per-trade feature snapshots from a TradingView strategy export when the Pine strategy writes compact metadata into an export-visible Signal or comment field. The version 1 wire format is:

```text
sl1|key=value|key=value
```

The `sl1` marker is required. Put it at the beginning of the field so the payload is unambiguous and future formats can use a different marker.

## Safe Keys And Values

Keep the format deliberately small and flat:

- Use lowercase `snake_case` keys made from ASCII letters, digits, and underscores. Start a key with a letter; for example, `setup`, `rvol`, or `qqq_above_vwap`.
- Give each key one scalar value. Supported useful values are booleans, null, numbers, and short strings.
- Do not put `|`, a newline, or another `=` in a value. Version 1 has no quoting or escaping layer.
- Do not repeat a key in one payload. When several export fields provide the same key, the deterministic conflict rules below apply.
- Keep payloads compact. Store a feature snapshot needed to explain the trade, not prose, secrets, or an entire indicator history.
- Use stable units in key names when they are not obvious, such as `atr_pct=1.4` or `distance_vwap_r=0.35`.

Examples:

```text
sl1|setup=vwap_reclaim|rvol=1.82|qqq_above_vwap=true|opening_range_break=false
sl1|exit_reason=tp1|mfe_r=1.35|scaled_out=true
sl1|regime=trend|earnings_days=null|score=4
```

For an entry Signal value, the metadata can be the order identifier itself:

```text
sl1|side=long|setup=orb_retest|rvol=2.15
```

For an export-visible comment, put the human meaning in a key instead of adding unstructured text around the marker:

```text
sl1|exit_reason=eod|stop_moved=true
```

Whether TradingView exports an order ID, Signal, or comment depends on the Pine order function and export shape. Confirm the payload appears in the CSV before relying on it.

## Parsing And Merge Behavior

For each paired trade, Strategy Lab checks export-visible text in this fixed order:

1. Entry Signal
2. Entry comment
3. Exit Signal
4. Exit comment

Recognized `sl1` payloads are merged into one flat feature snapshot. The first value for a key wins. A different value for the same key in a later field does not overwrite it; the preview emits a conflict warning so the strategy can be corrected. This makes entry-time features authoritative when the same key also appears on the exit.

Values are coerced conservatively for storage in JSON:

- `true` and `false` become booleans.
- `null` becomes JSON null.
- Integer and decimal strings become JSON numbers when conversion is reasonable and does not discard meaningful formatting.
- Everything else stays a string.

Malformed metadata produces preview warnings rather than silently changing a value or dropping an otherwise valid trade. Unknown keys are allowed; Strategy Lab does not maintain a global feature schema in this stage.

## Preview And Commit Workflow

TradingView exports timestamps without a reliable timezone. Every preview and import therefore requires an explicit IANA source timezone such as `America/New_York`. Strategy Lab interprets the source timestamps in that zone, normalizes them to UTC for storage, and retains the raw timestamp strings and source timezone for auditability. Do not infer a timezone from a symbol, filename, browser locale, or an `EOD` signal.

Import is intentionally a two-step process:

1. Send multipart fields `strategy_version_id`, `source_timezone`, and `file` to `POST /strategy-lab/imports/preview`. Preview makes no database writes. It returns `source_sha256`, `version.source_fingerprint`, and `preview_fingerprint` along with the header mapping, accepted/rejected trade counts, normalized trade samples, and warnings.
2. Review the pairing, timestamps, values, and warnings. A preview with rejected groups cannot be committed.
3. Re-upload the same file to `POST /strategy-lab/runs/import`. Its multipart `metadata` field is JSON containing `strategy_version_id`, `expected_source_sha256`, `expected_version_fingerprint`, `expected_preview_fingerprint`, the same `source_timezone`, and required `symbol` and `timeframe` values. Optional run fields are `backtest_start`, `backtest_end`, `initial_capital`, `currency`, `extended_hours`, and `notes`.

The source hash binds the upload bytes, the version fingerprint binds the exact result-producing strategy version, and the preview fingerprint is the binding token that joins those values with the selected timezone. If the file, timezone, or version changes, preview again. Commit reparses the upload and verifies all three before writing the run and trades atomically. A source file can be imported only once for the same strategy version; duplicate detection uses the strategy-version/source-hash pair.

If backtest bounds are supplied, they must contain every imported entry and exit date after conversion to the source timezone. Bounds are research metadata, not a filter: commit will not silently drop out-of-range trades.

### Curl Verification

Set `VERSION_ID` and `CSV`, then preview:

```bash
VERSION_ID=00000000-0000-0000-0000-000000000000
CSV=/absolute/path/to/tradingview.csv
curl -sS -X POST http://localhost:8000/strategy-lab/imports/preview \
  -F "strategy_version_id=${VERSION_ID}" \
  -F "source_timezone=America/New_York" \
  -F "file=@${CSV}"
```

Copy `source_sha256`, `version.source_fingerprint`, and `preview_fingerprint` from that response into the variables below, then commit the unchanged file:

```bash
SOURCE_SHA256=copy-from-preview
VERSION_FINGERPRINT=copy-from-preview
PREVIEW_FINGERPRINT=copy-from-preview
curl -sS -X POST http://localhost:8000/strategy-lab/runs/import \
  -F "file=@${CSV}" \
  --form-string "metadata={\"strategy_version_id\":\"${VERSION_ID}\",\"expected_source_sha256\":\"${SOURCE_SHA256}\",\"expected_version_fingerprint\":\"${VERSION_FINGERPRINT}\",\"expected_preview_fingerprint\":\"${PREVIEW_FINGERPRINT}\",\"source_timezone\":\"America/New_York\",\"symbol\":\"NBIS\",\"timeframe\":\"5m\"}"
```

A successful commit returns HTTP `201`. Changing the CSV bytes, timezone, or strategy version after preview should return a conflict and require a fresh preview.

Imported simulations stay in `strategy_run` and `strategy_run_trade`. They never become journal `fill`, `trade`, or `tradefill` rows and never pass through FIFO reconstruction.

## Stage 4 Frontend Workflow

The `/strategy-lab` UI now supports strategy creation, version history, and exact Pine source/assumption pages. Start an import from a version page so the selected version, source fingerprint, and hypothesis stay visible. The import screen submits the preview request, displays detected mappings, counts, warnings, rejected groups, and normalized trade samples, then commits only the same selected file and returned bindings.

After commit, the UI opens the run page. Run history and detail use `GET /strategy-lab/runs` and `GET /strategy-lab/runs/{run_id}`; the simulated-trade table uses paginated/filterable `GET /strategy-lab/runs/{run_id}/trades`. The page also exposes explicit metric recalculation, coverage, long/short and time-bucket summaries, and equity/drawdown curves. Stage 4 reused Alembic revision `f1a2b3c4d5e6` and added no schema migration.

## Current Limitations

- The importer targets TradingView's paired strategy export: rows with the same trade number must resolve to exactly one Entry and one Exit. Exit-before-entry file order is accepted, but missing, duplicate, scaled, or multi-leg rows are rejected explicitly. Commit blocks the entire file when any trade group is rejected; it never creates a partial research run.
- Trade-level PnL, return, excursion, and cumulative values are taken from the paired export. When TradingView repeats those values across Entry and Exit rows, disagreements are surfaced as warnings.
- Metadata is flat. Nested JSON, arrays, quoted delimiters, and escaped values are not supported by `sl1`.
- Metadata quality depends on what the Pine script emits at order time. The importer cannot reconstruct indicators that were not exported.
- Versioned run metrics and the end-to-end single-run frontend are available. Two-run comparison, deterministic findings, experiment workflows, and Pine diffs remain Stage 5 work.
