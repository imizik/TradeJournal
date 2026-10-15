# Bounded repeatable invented advisor questions

Selected October 11, 2026. The connected #251 trial remains owned by the
existing advisor chat; its passing CI/native evidence does not establish
activation or actual Jo acceptance. This successor is implementation only.

## Owner flow and immutable scope

From `/advisor-review` → `/advisor-review/questions`, the authenticated owner can create and assign an explicit
invented question and plan, list pending/answered/revoked/expired assignments,
reopen each original request and receipt, and revoke one assignment. Creation
requires confirming that the text contains invented scenario information only.
Use the existing pinned invented packet; no new capture, provider, model call,
real journal data, shadow choices, schedules or paper actions. Maximum 20
questions per isolated fixture. A new question gets a fresh UUID, thirty-minute
expiry and request hash, even with identical text. Its original packet never
changes. No edits or deletion; revocation preserves answers.

The existing fixture call's JSON stores the bounded assignment ledger; the
existing A3 one-attempt-per-day reservation and schema remain unchanged. Each
entry uses the existing handoff shape, citation validator and receipt hashes.
The original single-request record stays intact and recoverable. One new
assignment is selected at a time. Creating another is refused while the selected
request is pending and active; answer or revoke it first. Selecting a new request
ends connector access to earlier ones; their owner recovery remains available.

## Authority and transaction boundary

An explicit disabled-by-default `assignment_management` option and pinned
`owner_peer_uid` enable fixed owner list/create/revoke routes on the existing
isolated Unix bridge. Only the dedicated authenticated frontend's kernel Unix
peer UID may call them; bearer, cookie, gateway and claimed identity headers are
rejected. The BFF requires the existing enabled owner session, exact origin and
session CSRF for writes, bounded JSON, and its separately pinned backend socket.
It forwards no browser or OAuth credentials. The legacy read-only owner service,
UID, ACL and routes remain unchanged. No management route joins the public MCP
catalog or main private API. Adapter UID must differ from owner frontend UID.

OAuth identity/config remain fixed. The same three advisor tools resolve the
selected assignment from the ledger on every request. The submitted packet and
request hashes must match it under the shared SQLite writer lock; a delayed
answer cannot bind to a newer question. Revocation, creation and save serialize
on that lock. Assignment expiry, config disablement and OAuth authority are
rechecked before commit. Exact active retries recover the original receipt;
changed answers conflict. Before committing a new request or answer, reserve
the complete 64 KiB owner-response budget for all 20 future summaries (including
JSON escaping), and check the complete MCP read response. A too-large answer
rolls back rather than creating an unrecoverable receipt. After an uncertain owner write, reload and inspect
saved state; never automatically resubmit. A create operation UUID makes an
explicit identical retry idempotent. Revoked assignments cannot be reactivated.

## Activation and acceptance

Merging ships dormant source only. The existing #251 installation/activation
packet is unchanged and does not enable management. Later activation must review
the exact runtime, fixed frontend UID, backend socket named-user connect grant
and read-only socket mount, config flags and frontend socket settings. No broad
API exposure, journal grant change or owner-reader write grant is permitted.
Stop both advisor socket/process pairs before runtime replacement; keep the
ledger. Disabling management hides its owner routes and restores the original
pinned connector binding without deleting managed receipts. Do not roll back to
older source while a managed question is assigned; stop the entrance first.

Fixture acceptance covers two distinct assignments through unchanged running
processes/OAuth configuration, cited saved answer equality after reload/reopen
and process replacement, stale-hash/foreign-peer/CSRF denials, concurrent
save/revoke behavior and preserved prior receipts. Inspect desktop and 390px UI.
Actual signed-in Jo transmission, retained native permissions, approved service
restart and production activation remain separately named acceptance layers.
