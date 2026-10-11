# Troubleshooting the integration boundary

Use fresh evidence to select the failing layer. These are recovery patterns from
the trials, not authorization to change services or account permissions.

| Observation | Next bounded step |
| --- | --- |
| Browser stops responding while the host may be asleep | Request wake/sign-in handoff and continue independent preparation. Do not repeatedly click or infer an authentication failure. |
| Locator or accessibility index fails after a page change | Read current page state and retarget the visible control. A failed receipt-expansion click is not a reason to repeat replay or save. |
| Login prompt disagrees with an apparently signed-in page | Check the displayed identity and a fresh authorized read in the relevant browser. Local sign-in does not prove the cloud browser is authenticated. |
| OAuth discovery fails | Check public DNS/TLS and metadata routing separately from issuer/client/callback configuration. Never bypass TLS or introduce an unauthenticated data route. Metadata alone does not prove tool access. |
| Reconnect returns unauthorized or a wrong assignment | Inspect the fresh identity/catalog; reconnect the intended same account only within authorization. Stop on wrong identity, scope or assignment instead of widening access. |
| Public-key snapshot or fixture/export expired | Use the contract's approved refresh/restaging mechanism, then verify its age and binding. Do not relax TTL or revive old grants. |
| Save response was lost | Retrieve the immutable receipt before an exact retry. Changed content is a conflict, not a retry; do not try a different entry point to create another choice. |
| Dates appear inconsistent | Compare timezone and semantic clock: cutoff, retrieval, deadline and receipt. Compare only the precision actually displayed. |
| Packaged files differ from the manifest | Inspect for metadata files such as AppleDouble `._` entries; package without host metadata and recheck exact inventory/digests. Do not accept unexplained extras or broadly delete files. |
| Proxy validation rejects a new stanza | Restore the previously valid configuration if already edited, fix the new stanza, and validate again before reload. Preserve unrelated routes and existing administration settings. |
| A denial test receives HTTP 401/403 before a tool envelope | Verify authorization refusal and absence of data; do not require a successful HTTP response containing `isError`. Follow the contract's expected boundary. |
| A native isolation probe fails or its diagnostics disappear | Retain the non-secret child error and exit status before cleanup. Use disposable CI and positive controls to distinguish sandbox enforcement from ordinary file permissions; never run destructive policy-removal probes on a retained server. |

An expired token, stale UI and failed transport can look similar. Record the
observed failure layer and stop dependent mutations until identity and state are
clear. Do not copy tokens, cookies, secrets or raw account-page dumps into logs.
