# OAuth setup without repeated navigation

Use the selected repository contract for identity isolation, audiences, scopes,
token/key age and activation gates. This reference supplies operator shortcuts,
not new permission. Store live bindings and evidence in a private task record;
never copy tenant names, callbacks, client IDs, subjects or secrets into skills.

## Check blockers before creating resources

- Check for an existing authorized admin API/CLI or signed-in dashboard. Do not
  create broader admin/M2M grants just to automate setup. Hand login to the user
  immediately if needed, and continue independent local preparation.
- Inspect application/API capacity and the actual Create controls before
  proposing credential creation. Provider quotas may count SSO integrations or
  automatically generated test apps as well as the visible application list.
- Capture the new connector form's exact callback and client-authentication
  settings. Do not reuse an old callback or assume a common redirect URI. If
  discovery must be live before the callback is visible, present that bounded
  dependency explicitly; do not start services to get past it without approval.
- Prepare exact names, audience, callback, grant types, scopes and access policy
  together. Separate confirmed values from provider-assigned IDs still pending.
  Check current provider/OpenAI documentation only for unresolved behavior;
  retain its links instead of repeating discovery at each handoff.

## Create only the intended bindings

For Auth0, inspect user-flow and client-flow access policies separately. An
interactive advisor connection needs its approved user-flow scopes, not a
machine-to-machine grant. Regular web apps may default to extra grant types;
constrain the new app before issuing tokens or authorizing API access. Keep
"always grant all" off when the contract specifies a fixed scope set. API
permission definitions and an application's authorized scopes are different;
verify both.

API creation may generate a test companion application. Check for that side
effect before spending another slot. Do not silently reuse or delete existing
apps, or assume permission to delete a companion. Obtain exact deletion
authorization where required by scope/tool policy, including after an automatic
approval rejection. Record the reason and stop that action; no indirect bypass.
An unneeded companion with denied access can remain disabled pending a decision.

After Save/Create/Delete, use one fresh persisted read to establish the result.
An unsaved banner is not proof of persistence. A scope-grant action may commit
immediately even when the outer Save button is disabled. Read back before
resubmitting an uncertain mutation. If quota controls remain stale after a
confirmed deletion, offer one user refresh rather than deleting more apps or
polling indefinitely. Compare unaffected bindings only where a concrete risk
requires it; lack of logs alone does not prove an old app unused.

## Make the human step short and private

Prepare the supported form, list the exact remaining fields/actions, and pause
agent edits while the user owns it. Ask for a completion marker or sanitized
error, not credentials or screenshots of secret-bearing fields. For a new test
identity, use a separate login; an email-shaped identifier need not be called a
verified real email without evidence.

If verification mail is outside scope, use a supported suppression option. The
Auth0 Create via JSON UI supports `verify_email: false` for a database identity;
leave email/password blank for private human entry. The user must close/clear
the editor before returning control. Do not capture its DOM, screenshots,
clipboard or filled JSON after credential entry. Read only the resulting
public subject/connection from the profile. Keep client secrets in private
provider/connector UI, not chat, scripts, logs or a committed record.

## Finish the current gate

Record the actual API/client/subject IDs and persisted settings once. Reuse that
evidence until an input changes; do not claim actual PKCE, issued-token claims,
consent or Jo tool access from configuration alone. Keep approved credential
creation distinct from retained binding/assignment changes, public keys,
HTTPS publication and startup under the selected contract. Do not freeze a
short-lived trial early just to populate an approval packet. Preserve original
exports/receipts and use receipt-first recovery after an uncertain answer save.
