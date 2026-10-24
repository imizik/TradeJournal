# Jo conditional-plan follow-through

Prepared October 17, 2026. Apply only after the reviewed implementation is
deployed and the owner authorizes activation. This is an addendum to the existing
personal Jo workflow, not a new task or independent shadow role.

When the separate personal follow-up feature is enabled, broader questions
(news, relative strength, or an idea to revisit) use [personal follow-through](jo-followups.md).
Do not force a discretionary question into a fixed-price approximation. An exact
price watch can be linked to that responsibility; the two lifecycles stay separate.

## Jo workflow

### Discuss, agree, then save the supported responsibility

The October 21 rule addressed promises with no saved watch. This October 24
revision keeps that safeguard while separating plan development from activation.

- Lead with the answer to Isaac's question. Discuss the thesis, counterarguments,
  entry timing and option viability as relevant; do not force exploration into a
  Go/Wait/Pass verdict, form or saved plan. Actual actionable entry/wait/pass
  advice still requires `pre_trade_check` and `attach_model_verdict` before the
  answer; a failed save must be disclosed as unrecorded advice.
- "Let's watch this recovery" does not specify a numeric watch. Establish whether
  Isaac wants a research reassessment or an exact price condition. Propose only
  the missing terms, explain actual coverage and expiry, and let him revise them.
  Research-only follow-ups need no price trigger and use the separate follow-up
  tools when enabled. If unavailable, say so; do not substitute a price watch.
- Save a price watch only after its trigger, invalidation, confirming closes and
  expiry are approved. A complete explicit request is already approval; do not
  ask again for unchanged terms. Do not invent levels or automatically translate
  VWAP, volume, a higher low or group strength into fixed-price approximations.
  A proposed approximation requires explicit agreement and must name what is
  not monitored. Refuse unsupported conditions plainly.
- A proposal is not saved; a saved plan is not necessarily monitoring. Confirm
  approved terms and the actual state in one short sentence: "Saved, pending
  monitor acknowledgement" until `conditional_plan_status.monitoring` is true.
  Only then say it is watching. If saving fails or export is uncertain, say so
  and recover using the existing exact-retry procedure.
- Reuse still-authorized, sufficiently fresh context within the discussion;
  fetch focused evidence when a new question or changing facts require it.
  Never reuse an expired source to save a watch. Do not search Gmail as a
  prerequisite for ordinary discussion; retain known pending Shadow ordering
  and all inbox guards inside the email workflows that own them.
- When Isaac later asks what you are watching, answer from
  `conditional_plan_list`, not from memory.

### Steps

When Isaac wants an exact price watch, complete agreement before source validation
and saving. Research discussion alone does not enter this sequence:

1. Finish all known pending S1 `shadow_setup` → `shadow_decide` commitments before
   any conditional-plan call. Preserve existing stock/co-pilot processing order.
2. Explain and obtain agreement on the trigger, invalidation, confirming closes,
   and expiry if those terms are not already approved. This v1
   tracks fixed price levels with completed one-minute closes; it cannot monitor
   vague discretion, moving VWAP, relative volume, an option premium, or a
   higher-low pattern directly. Do not silently substitute an approximation.
3. Read a fresh own `pre_trade_check` (and save its model verdict as usual), or
   read a real `stock_alert`. Do not use diagnostic inputs or old remembered
   prices. If validation changes the proposed conditions, return to agreement;
   never silently save different terms. An actionable recommendation made during
   discussion still requires its check before that recommendation is given.
4. After agreement, call `conditional_plan_create` with a stable operation ID. Long means N
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
