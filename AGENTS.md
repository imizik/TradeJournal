# AGENTS.md

The working agreement for coding agents in this repository — Codex, Claude
Code, anything else — is [CLAUDE.md](CLAUDE.md). Read it first. Nothing in it
is Claude-specific, and it is deliberately the only copy: this file used to
hold a second one, and hand-editing both is how they drifted apart.

Durable knowledge about the system lives in `docs/agent/`. `CLAUDE.md` carries
the table saying which document answers what, and
[docs/agent/README.md](docs/agent/README.md) is the same index with longer
descriptions.

```bash
bash scripts/setup.sh           # clean clone -> runnable
bash scripts/verify.sh --fast   # while working
bash scripts/verify.sh          # before saying it works
bash startdev.sh                # run the app
```

The repository is the source of truth. If a document disagrees with the code,
the code wins and the document gets fixed in the same change.
