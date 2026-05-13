"""Config loading: YAML on disk → validated PebbleConfig.

Also verifies that the env vars required by the chosen providers are
present, surfacing a `ConfigError` with an actionable message instead
of letting a missing key surface as a 401 hours later.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

from pebble.config.schema import PebbleConfig
from pebble.core.errors import ConfigError

DEFAULT_CONFIG_FILENAME = "config.yaml"

# provider → required env var
PROVIDER_ENV_VARS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
}


def load_config(path: Path | None = None) -> PebbleConfig:
    """Load config from `path`. If `path` is None, look for `./config.yaml`.

    If neither path is given nor `./config.yaml` exists, returns the schema's
    defaults — useful for tests and the vertical-slice-style first run.
    """

    load_dotenv()
    raw: dict[str, object] = {}
    if path is None:
        candidate = Path.cwd() / DEFAULT_CONFIG_FILENAME
        if candidate.is_file():
            path = candidate

    if path is not None:
        if not path.is_file():
            raise ConfigError(f"config file not found: {path}")
        with path.open("r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        if not isinstance(loaded, dict):
            raise ConfigError(f"config file must be a YAML mapping: {path}")
        raw = loaded

    try:
        config = PebbleConfig.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(f"invalid config:\n{e}") from e

    _require_env_for_providers(config)
    return config


def _require_env_for_providers(config: PebbleConfig) -> None:
    needed: set[str] = set()
    for provider in {config.embeddings.provider, config.llm.provider}:
        env_var = PROVIDER_ENV_VARS.get(provider)
        if env_var is None:
            raise ConfigError(f"unknown provider: {provider!r}")
        if not os.environ.get(env_var):
            needed.add(env_var)
    if needed:
        joined = ", ".join(sorted(needed))
        raise ConfigError(f"missing required env var(s) for configured providers: {joined}")
