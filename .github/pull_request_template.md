<!--
Prompts, not a form. Delete what does not apply; prose beats checkboxes.
The one section worth never deleting is "Verified".
-->

## What changed, and why

## Verified

<!--
`bash scripts/verify.sh` (or `--fast`, and say which). Then the part that
matters: what did you do that would have FAILED if the change were wrong?
Planting the defect and watching the check catch it is the standard here --
see docs/agent/verification.md, "Two rules every check must satisfy".
-->

## Not covered

<!--
Where this change lands outside the suite: frontend rendering, a live external
integration, anything you could not make fail where you ran it. Saying "none"
is fine when it is true. Claiming coverage you do not have is the thing this
section exists to prevent.
-->

## Docs

<!--
Updated, or confirmed none needed -- and which. The rule in CLAUDE.md is that
a document disagreeing with the code gets fixed in the same change; this line
is where that gets remembered. docs/agent/: architecture, domain-rules,
verification, environments, feature-map, roadmap. README for anything a
newcomer runs. Mechanical rot (dead paths, dead anchors) is already covered by
backend/tests/test_docs_links.py -- this is about claims that are now untrue.
-->
