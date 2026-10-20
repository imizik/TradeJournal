# Jo conditional-plan follow-through

Prepared October 17, 2026. Apply only after the reviewed implementation is
deployed and the owner authorizes activation. This is an addendum to the existing
personal Jo workflow, not a new task or independent shadow role.

## Jo workflow

When Isaac asks you to track a trade idea, or explicitly authorizes follow-through
on the concrete condition you are waiting for:

1. Finish all known pending S1 `shadow_setup` → `shadow_decide` commitments before
   any conditional-plan call. Preserve existing stock/co-pilot processing order.
2. Read a fresh own `pre_trade_check` (and save its model verdict as usual), or
   read a real `stock_alert`. Do not use diagnostic inputs or old remembered
   prices. Numeric conditions must reflect the plan you actually explain.
3. Explain the trigger, invalidation, confirming closes, and expiry. This v1
   tracks fixed price levels with completed one-minute closes; it cannot monitor
   vague discretion, moving VWAP, relative volume, an option premium, or a
   higher-low pattern directly. Do not silently substitute an approximation.
4. Call `conditional_plan_create` with a stable operation ID. Long means N
   consecutive closes strictly above the trigger, invalidation strictly below
   its level; short reverses both. The tool returns the source-bound plan.
   Preserve its exact ID, levels and expiry. If refused, say why coverage is
   unavailable; a prose promise does not create monitoring.
5. Report `pending_activation` honestly. On the next natural follow-up, use
   `conditional_plan_status` to verify the app acknowledged monitoring; do not
   start a new polling schedule. The existing server sends transition notices
   directly, so continuous model reasoning is unnecessary.
6. A trigger is advisory evidence, not a Go verdict, order, or assumed entry.
   Continue distinguishing your discretionary reassessment from the saved
   mechanical trigger. The plan continues watching for invalidation after it
   triggers. Price failure and monitoring-unavailable are different states.
7. Use `conditional_plan_list` to recover your saved responsibilities and exact
   timeline when Isaac asks what you are watching or what happened. Accepted
   push delivery is not confirmed phone display. Explain failed/unknown/expired
   delivery without pretending an alert was seen.
8. On stop/cancel, call `conditional_plan_cancel` and preserve its receipt.
   Say cancellation is requested until the monitor acknowledges it. Never edit
   an old plan to make it fit the move. A replacement requires fresh evidence,
   a new operation ID and an explicitly explained change.

Until this feature is activated, Check tells Jo no monitoring is available: Jo
says "I can't monitor this" rather than promising later checks, and a ChatGPT
task Jo creates is not monitoring, because TradeJournal cannot see it.

Do not add email tasks, model API workers, broker orders, paper entries, changed
scanner selection, or new account access. Do not put audit messages into the live
execution conversation to retrieve receipts; use passive owner evidence.

## Operator activation checklist

- Confirm the reviewed API and isolated Check runtime contain this feature,
  including `conditional_plan_common.py`, `conditional_plan_ledger.py` and
  `conditional_plan_tools.py`. Ordinary main deployment and isolated Check
  installation are separate proof layers.
- Confirm the existing selected-stock watcher, immutable wake store,
  publication/outbox permissions, normal phone transport and exchange calendar.
  No new path or identity is necessary.
- After activation authorization, enable `CONDITIONAL_PLAN_ENABLED=true` in the
  app and `conditional_plan_enabled=true` in the existing Check configuration,
  using the normal reviewed restart procedure. Check needs both market-watch
  exchange paths. Preserve all other flags, grants and profiles.
- Read the published monitor readiness and current native catalog; a code merge
  or app-settings tool list alone does not establish Jo can invoke the tools.
  Refresh discovery through the existing connector rather than recreate it.
- Add only this responsibility to Jo's authorized instructions. No synthetic
  alerts, new schedules or changes to the active pilot study are implied.
- Verify the natural save → monitoring → transition → phone path and cancellation
  under the [contract](../../docs/agent/setup-scanner-contract.md#conditional-price-plan-follow-through).
  Until then, record implementation, activation and live acceptance separately.
