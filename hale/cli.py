"""Command line entry point: `hale ask`, `hale experiments`, `hale tools`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hale import __version__
from hale.config import ConfigError, Settings
from hale.policy import RepoPolicy
from hale.tools import default_registry


def _policy(settings: Settings) -> RepoPolicy:
    return RepoPolicy(
        settings.target_repo,
        allow_test_role=settings.allow_test_role,
        python=settings.python,
    )


def _settings(args: argparse.Namespace) -> Settings:
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        if args.repo is None:
            raise SystemExit(f"hale: {exc}") from exc
        settings = Settings(target_repo=Path(args.repo).expanduser().resolve())
    if args.repo is not None:
        settings = Settings(**{**settings.__dict__, "target_repo": Path(args.repo).expanduser().resolve()})
    return settings


def cmd_ask(args: argparse.Namespace) -> int:
    from hale.agent import Agent
    from hale.ollama import OllamaError

    settings = _settings(args)
    agent = Agent(settings)
    try:
        result = agent.ask(" ".join(args.question))
    except (OllamaError, RuntimeError) as exc:
        raise SystemExit(f"hale: {exc}") from exc
    print(result.answer)
    if args.verbose:
        print(
            f"\n[hale] steps={result.steps} stop={result.stop_reason} "
            f"tokens_in={result.input_tokens} tokens_out={result.output_tokens}",
            file=sys.stderr,
        )
        for step in result.trace:
            for call in step["tool_calls"]:
                print(f"[hale] step {step['step']}: {call['name']}({json.dumps(call['input'], ensure_ascii=False)})", file=sys.stderr)
    return 0


def cmd_experiments(args: argparse.Namespace) -> int:
    settings = _settings(args)
    policy = _policy(settings)
    outcome = default_registry().call(policy, "list_experiments", {})
    if not outcome["ok"]:
        print(json.dumps(outcome, indent=2), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(outcome["result"], indent=2, ensure_ascii=False))
        return 0
    for exp in outcome["result"]["experiments"]:
        version = f"v{exp['latest_version']}" if exp["latest_version"] is not None else "-"
        print(f"{exp['id']:32} {version:5} {exp['status'] or '-':45} {exp['latest_path']}")
    return 0


def cmd_tools(_: argparse.Namespace) -> int:
    for schema in default_registry().schemas():
        print(f"{schema['name']}\n  {schema['description']}\n")
    return 0


def cmd_scripts(args: argparse.Namespace) -> int:
    settings = _settings(args)
    outcome = default_registry().call(_policy(settings), "list_scripts", {})
    if not outcome["ok"]:
        print(json.dumps(outcome, indent=2), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(outcome["result"], indent=2, ensure_ascii=False))
        return 0
    for spec in outcome["result"]["scripts"]:
        confirm = "confirm" if spec["confirm"] else "auto"
        present = "yes" if spec["present"] else "missing"
        print(f"{spec['name']:32} {spec['family']:6} {confirm:8} {present:8} {spec['description']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hale", description="Hale: Helio24 research agent.")
    parser.add_argument("--version", action="version", version=f"hale {__version__}")
    parser.add_argument("--repo", help="Target repository path (overrides HALE_TARGET_REPO).")
    sub = parser.add_subparsers(dest="command", required=True)

    ask = sub.add_parser("ask", help="Ask a question about the target repository.")
    ask.add_argument("question", nargs="+")
    ask.add_argument("-v", "--verbose", action="store_true", help="Print tool calls and usage to stderr.")
    ask.set_defaults(func=cmd_ask)

    exps = sub.add_parser("experiments", help="List versioned protocols without calling a model.")
    exps.add_argument("--json", action="store_true")
    exps.set_defaults(func=cmd_experiments)

    tools = sub.add_parser("tools", help="List the tools exposed to the model.")
    tools.set_defaults(func=cmd_tools)

    scripts = sub.add_parser("scripts", help="List allowlisted Helio24 scripts.")
    scripts.add_argument("--json", action="store_true")
    scripts.set_defaults(func=cmd_scripts)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
