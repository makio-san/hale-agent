# Hale: Helio24 Research Agent

Hale is a research agent for [Helio24](https://github.com/makio-san/helio24),
a preregistered solar flare forecasting project. It reads the project's
protocols, reports and frozen artifacts, answers questions with file-level
citations, and will later propose and run preregistered experiments behind
human approval gates.

The name refers to George Ellery Hale, who first measured magnetic fields in
sunspots in 1908. Helio24 predicts flares from exactly those magnetic
measurements.

## Why an agent, when Helio24 already has scripts for everything?

Helio24 contains the whole research loop as deterministic tools: `run_*`,
`report_*`, `audit_*` and `check_*` scripts, versioned protocol JSON files
with `supersedes` links, hash-verified frozen artifacts and a bilingual report
publisher with numerical parity checks. What it does not contain is the layer
that decides which tool to use next, drafts the next protocol, interprets a
result strictly against the acceptance rule frozen before the run, and
remembers what seventy reports concluded. Today that layer is the human
researcher. Hale is an attempt to encode it, with the same discipline:
preregistration, immutability, and human gates before any model fit and any
merge.

An agent that runs unlimited experiments is a p-hacking machine. Hale is
designed to be the opposite: it cannot read the reserved test period, cannot
edit a frozen artifact, and cannot change an acceptance rule after a result
exists. See [`POLICY.md`](POLICY.md).

## Status

Stage 1, read-only research memory, is implemented:

| Tool | What it does |
| --- | --- |
| `list_experiments` | Groups `config/*.json` protocols by id, latest version and status |
| `get_experiment` | Returns one protocol plus the report index entries that refer to it |
| `search_reports` | Finds a phrase across `docs/**/*.md` with path and line number |
| `read_document` | Reads a line range of a report or protocol |
| `read_artifact` | Reads `report.json` keys or `metrics.csv` rows of a frozen artifact |

Every tool goes through `hale.policy`, which allows only the paths listed in
`POLICY.md` and redacts reserved test sections. Policy violations are returned
to the model as data so it can recover and explain, never as exceptions.

## Setup

Requires Python 3.11 or newer, a local Helio24 checkout and an Anthropic API key.

```sh
git clone https://github.com/makio-san/hale-agent
cd hale-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

export HALE_TARGET_REPO=~/path/to/helio24
export ANTHROPIC_API_KEY=...
```

Optional settings:

| Variable | Default | Meaning |
| --- | --- | --- |
| `HALE_MODEL` | `claude-sonnet-4-5` | Model id passed to the Messages API |
| `HALE_MAX_STEPS` | `12` | Maximum model calls per question |
| `HALE_TOKEN_BUDGET` | `120000` | Input plus output tokens per question |
| `HALE_TRACE_DIR` | unset | If set, writes one JSON trace per run |
| `HALE_ALLOW_TEST_ROLE` | unset | `1` lifts test-role redaction; for final-test reporting only |

## Usage

```sh
hale experiments                 # list protocols, no model call
hale tools                       # show the tool surface exposed to the model
hale ask "Why is experiment5 still waiting for its test run?"
hale ask -v "Which hard-negative years regressed?"   # prints tool calls to stderr
```

`--repo PATH` overrides `HALE_TARGET_REPO` for a single command.

## Tests

```sh
pytest
```

The suite builds a small Helio24-shaped fixture repository and a scripted fake
model client, so it runs without network access or an API key. It covers path
allowlisting, symlink escapes, test-role redaction, every tool, and the loop's
step and token limits.

## Roadmap

1. **Read-only research memory** (done). Questions answered with citations.
2. **Typed script wrappers.** `run_*`, `report_*`, `audit_*` and `check_*`
   become tools restricted to development roles and fresh output directories.
3. **Preregistered experiment loop.** `propose_protocol` writes a new
   `config/<id>-vN.json` with hypothesis, acceptance rule and `supersedes`;
   a human approves; Hale runs, interprets only against the frozen rule,
   drafts the bilingual report, runs parity checks and tests, and opens a pull
   request; a human merges.
4. **Replay evaluation.** Helio24's commit history is a benchmark: give Hale
   the repository as it stood before each archived decision and measure whether
   it proposes, accepts and rejects the same way, never touches the test role,
   and reports numbers that match the artifacts.
5. **Report.** Publish the replay results, in Turkish and English, as a Helio24
   research report.

## License

MIT.
