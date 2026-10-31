# Hale: Helio24 Research Agent

Hale is a research agent for [Helio24](https://github.com/makio-san/helio24),
a preregistered solar flare forecasting project. It reads the project's
protocols, reports and frozen artifacts, answers questions with file-level
citations, and proposes the next preregistered experiment behind human
approval gates.

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

Stages 1 to 4 are implemented. Hale cannot approve its own protocol or merge
a pull request.

| Tool | What it does |
| --- | --- |
| `list_experiments` | Groups `config/*.json` protocols by id, latest version and status |
| `get_experiment` | Returns one protocol plus the report index entries that refer to it |
| `search_reports` | Finds a phrase across `docs/**/*.md` with path and line number |
| `read_document` | Reads a line range of a report or protocol |
| `read_artifact` | Reads `report.json` keys or `metrics.csv` rows of a frozen artifact |
| `list_scripts` | Lists the Helio24 scripts Hale may run, with required flags |
| `run_script` | Runs one allowlisted script into a new `artifacts/<name>` directory |
| `propose_protocol` | Writes `config/<id>-vN.json` with a frozen hypothesis and acceptance rule |
| `interpret_result` | Accepts or rejects a run only against that frozen rule |
| `draft_report` | Writes a new bilingual `docs/<id>.md` and `docs/<id>.tr.md` pair |
| `register_report` | Appends one row to `docs/reports.json` |
| `open_pull_request` | Opens a review PR; never merges |
| `hale replay` | Scores those tools against archived Helio24 decisions. No model call |

Every tool goes through `hale.policy`, which allows only the paths listed in
`POLICY.md` and redacts reserved test sections. Policy violations are returned
to the model as data so it can recover and explain, never as exceptions.

## Setup

Requires Python 3.11 or newer, a local Helio24 checkout and [Ollama](https://ollama.com).
`hale ask` calls a local model. No API key is required.

```sh
git clone https://github.com/makio-san/hale-agent
cd hale-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

ollama pull qwen2.5:7b
export HALE_TARGET_REPO=~/path/to/helio24
hale ask "Why is experiment5 still waiting for its test run?"
```

Optional settings:

| Variable | Default | Meaning |
| --- | --- | --- |
| `HALE_PROVIDER` | `ollama` | `ollama` or `anthropic` |
| `HALE_MODEL` | `qwen2.5:7b` | Ollama model tag, or a Claude model id when the provider is anthropic |
| `HALE_OLLAMA_HOST` | `http://127.0.0.1:11434` | Local Ollama server |
| `HALE_MAX_STEPS` | `12` | Maximum model calls per question |
| `HALE_TOKEN_BUDGET` | `120000` | Input plus output tokens per question |
| `HALE_TRACE_DIR` | unset | If set, writes one JSON trace per run |
| `HALE_ALLOW_TEST_ROLE` | unset | `1` lifts test-role redaction; for final-test reporting only |
| `HALE_PYTHON` | `<repo>/.venv/bin/python` | Interpreter used by `run_script` |
| `HALE_ALLOW_GIT` | unset | `1` allows `open_pull_request` after a human pull_request approval |

Set `HALE_PROVIDER=anthropic` and install `pip install 'hale-agent[anthropic]'` to use the Claude API instead. That path needs `ANTHROPIC_API_KEY` and is billed by Anthropic.

## Usage

```sh
hale experiments                 # list protocols, no model call
hale scripts                     # list allowlisted Helio24 scripts
hale tools                       # show the tool surface exposed to the model
hale proposals                   # list recorded human approvals
hale approve --gate protocol config/experiment5-v9.json
hale replay                      # score Hale against archived Helio24 decisions
hale replay --lock-repo ~/path/to/helio24   # also lock gold numbers to the live checkout
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
allowlisting, symlink escapes, test-role redaction, every tool, script
execution into a new artifact directory, frozen acceptance rules, bilingual
numeric parity, human approval gates, replay of archived Helio24 decisions,
and the loop's step and token limits.

## Roadmap

1. **Read-only research memory** (done). Questions answered with citations.
2. **Typed script wrappers** (done). `check_*`, selected `run_*` and `audit_*`
   scripts run through `run_script` into a new `artifacts/` directory.
   `run` needs `confirm=true` and `hale approve --gate protocol`. `audit` needs
   `confirm=true`.
3. **Preregistered experiment loop** (done). `propose_protocol` writes a new
   `config/<id>-vN.json` with hypothesis, acceptance rule and `supersedes`; a
   human approves; Hale runs, interprets only against the frozen rule, drafts
   the bilingual report, registers it, and opens a pull request. Hale does not
   merge. A human reviews and merges.
4. **Replay evaluation** (done). `hale replay` gives Hale a snapshot of the
   repository as it stood at each archived decision and scores whether it
   accepts and rejects the same way, keeps frozen fields, never reads the
   reserved test, and reports the published numbers exactly. `--repo` locks
   those gold values to the live Helio24 checkout. No model is called.
5. **Report.** Publish the replay results, in Turkish and English, as a Helio24
   research report.

## License

MIT.
