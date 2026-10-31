"""Runtime settings for Hale, read from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(RuntimeError):
    """Raised when required settings are missing or invalid."""


@dataclass(frozen=True)
class Settings:
    target_repo: Path
    provider: str = "ollama"
    model: str = "qwen2.5:7b"
    ollama_host: str = "http://127.0.0.1:11434"
    max_steps: int = 12
    max_output_tokens: int = 2048
    token_budget: int = 120_000
    trace_dir: Path | None = None
    allow_test_role: bool = False
    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        raw = env.get("HALE_TARGET_REPO")
        if not raw:
            raise ConfigError(
                "HALE_TARGET_REPO is not set; point it at a local Helio24 checkout."
            )
        target = Path(raw).expanduser().resolve()
        if not target.is_dir():
            raise ConfigError(f"HALE_TARGET_REPO does not exist: {target}")
        provider = env.get("HALE_PROVIDER", "ollama").strip().lower()
        if provider not in {"ollama", "anthropic"}:
            raise ConfigError("HALE_PROVIDER must be 'ollama' or 'anthropic'.")
        default_model = "qwen2.5:7b" if provider == "ollama" else "claude-sonnet-4-5"
        trace = env.get("HALE_TRACE_DIR")
        return cls(
            target_repo=target,
            provider=provider,
            model=env.get("HALE_MODEL", default_model),
            ollama_host=env.get("HALE_OLLAMA_HOST", cls.ollama_host).rstrip("/"),
            max_steps=int(env.get("HALE_MAX_STEPS", cls.max_steps)),
            max_output_tokens=int(env.get("HALE_MAX_OUTPUT_TOKENS", cls.max_output_tokens)),
            token_budget=int(env.get("HALE_TOKEN_BUDGET", cls.token_budget)),
            trace_dir=Path(trace).expanduser() if trace else None,
            allow_test_role=env.get("HALE_ALLOW_TEST_ROLE") == "1",
        )
