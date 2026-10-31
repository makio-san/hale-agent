# Hale operating policy

This document defines what Hale may do inside a target research repository.
The `hale.policy` module enforces the machine-checkable parts; the rest is a
contract for prompts, reviews and future tools. A change to this document is
a change to the agent and must be committed and reviewed like code.

## Principles

1. The agent never widens its own permissions. New capabilities are added by
   humans through new tools, each mapped to a rule below.
2. Acceptance rules are written before results exist. The agent interprets
   results only against the rule that was frozen for that experiment.
3. Frozen artifacts, published reports and protocol versions are immutable.
   Revisions create new files with `supersedes` links, never edits in place.
4. Every answer cites the file it came from. Unsupported claims are not
   answered; the agent says what is missing instead.

## Stage 1: read-only research memory

Allowed reads inside the target repository:

| Path pattern | Purpose |
| --- | --- |
| `README.md`, `AGENTS.md` | Project status and conventions |
| `docs/**/*.md`, `docs/reports.json` | Protocols, reports and the bilingual index |
| `config/*.json` | Versioned experiment protocols |
| `artifacts/*/report.json`, `artifacts/*/metrics.csv` | Frozen summary outputs |

Everything else is denied, including `data/`, raw Parquet or CSV rows,
notebooks, model files, environment files and anything outside the repository
root. Symbolic links that escape the root are denied.

### Reserved test boundary

Helio24 reserves a later test period that may be evaluated once, after all
development choices are frozen. Hale treats that boundary as follows:

- Protocol metadata about the test role (date ranges, status flags) is readable.
- Any artifact section keyed as a test role result (`test`, `test_*`,
  `reserved_test*`, `final_test*`) is denied unless the owning protocol's
  `status` declares the final test complete.
- Rows in `metrics.csv` whose `role` or `split` column is a reserved test
  label are omitted from tool results under the same rule.
- The agent may not run, request or suggest any command that reads test rows.

### Not allowed in Stage 1

- Writing or deleting any file in the target repository.
- Running scripts, notebooks or shell commands in the target repository.
- Network access other than the model API.
- Git operations in the target repository.

## Stage 2 (current): typed script wrappers

Hale may run a fixed catalog of `check_*`, `run_*` and `audit_*` scripts
through `run_script`. The catalog is code, not a prompt. A script that is
not in the catalog is denied even if the file exists.

Execution rules:

- The interpreter is the target repository's `.venv/bin/python`, or
  `HALE_PYTHON` when set.
- `--output` must be a new directory of the form `artifacts/<name>`. Existing
  directories are denied. Frozen artifacts are never overwritten.
- `--config` and `--protocol` must be readable `config/*.json` files.
- `--source`, `--materialized` and `--incumbent` must be existing
  `artifacts/<name>` directories.
- Protocols that set `development_data.reserved_test_rows: true` cannot be
  executed.
- `family=check` may run without confirmation. `family=run` and
  `family=audit` require `confirm=true` after an explicit user request.
- Report scripts that write under `docs/` are not wrapped in this stage.

After a check run, Hale may read `artifacts/<name>/preflight.json` under the
same reserved-test redaction rules as `report.json`.

## Later stages (not implemented)

Stage 3 adds `propose_protocol`, bilingual report drafting and pull request
creation behind two human gates: protocol approval before any model fits, and
merge approval after review. Stage 4 replays archived decisions to measure
whether the agent accepts and rejects the same candidates the human
researcher did.
