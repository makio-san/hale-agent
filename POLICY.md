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
| `artifacts/*/report.json`, `artifacts/*/metrics.csv`, `artifacts/*/preflight.json` | Frozen summary outputs |
| `artifacts/hale_approvals/*.json` | Human gate records written by `hale approve` |

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

## Stage 2: typed script wrappers

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
- `family=check` may run without confirmation. `family=run` requires
  `confirm=true` and a human protocol approval. `family=audit` requires
  `confirm=true`.
- Report scripts that write under `docs/` are not wrapped here; Stage 3
  drafts new report files instead.

After a check run, Hale may read `artifacts/<name>/preflight.json` under the
same reserved-test redaction rules as `report.json`.

## Stage 3: preregistered loop with human gates

Hale may create new protocol versions and new bilingual reports. It may not
approve them. Two CLI gates are the only way to unlock the next step:

```sh
hale approve --gate protocol config/<id>-vN.json
hale approve --gate pull_request config/<id>-vN.json docs/<id>.md docs/<id>.tr.md
```

Write rules:

- New files only: `config/<id>-v<N>.json`, `docs/<slug>.md`, `docs/<slug>.tr.md`.
- `docs/reports.json` may gain a new row. Existing rows cannot change.
- Frozen protocol fields cannot be altered in a proposal: roles, data
  contract, label inventory, measurement contract, development selection.
- `acceptance_rule` is frozen at propose time. `interpret_result` uses that
  rule only. A failed rule is a rejection.
- `open_pull_request` needs `HALE_ALLOW_GIT=1`, a pull_request approval, and
  `confirm=true`. It never merges.

Approvals live in `artifacts/hale_approvals/` and bind the SHA-256 of the
approved files. A later edit invalidates the approval.

## Stage 4 (current): replay evaluation

`hale replay` scores Hale against archived Helio24 decisions. It is an
evaluator, not a model tool, and it does not widen Hale's permissions.

Rules:

- Each case materializes an isolated snapshot. The live Helio24 checkout is
  not written and is not the default target.
- The encoded tools (`interpret_result`, `propose_protocol`, `read_artifact`,
  `run_script`) are scored against a frozen gold record: accept or reject,
  frozen protocol fields, reserved-test denial, and exact numbers.
- `--repo` is a read-only lock: published Helio24 files must still contain
  the gold numbers and phrases. Missing `artifacts/` files are skipped.
  Missing `config/` or `docs/` files fail the lock.
- Replay does not call a model, does not approve protocols, and does not
  merge pull requests.

## Later stages (not implemented)

Stage 5 publishes the replay results, in Turkish and English, as a Helio24
research report.
