# Retired TradingView alert-loop plan

> Retired by Charts C5.2 on 2026-10-06 after the user observed an in-house
> level alert arrive on the phone. This file remains as a historical pointer,
> not an implementation guide.

C5.2 removed the webhook ingress, the Pine alert source and the private
analysis-worker autostart. Current releases expose only private GET routes for
existing `tradingview_alert` rows. The rows, table, migration and Signals pages
remain read-only. The old ingress configuration, OS account and database role
are preserved; removing them requires a separate operator decision.

The historical v1 payload and parser behavior remain documented in
[TradingView webhook contract v1](tradingview-webhook-contract-v1.md). The
current retirement contract and acceptance checks are in the
[Charts roadmap](charts-roadmap.md#phase-5--alerts-on-the-chart).
