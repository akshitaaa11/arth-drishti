from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[3] / ".env", override=False)

ROOT_DIR = Path(__file__).resolve().parents[3]
CONFIG_DIR = ROOT_DIR / "config"


def _read_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if value is not None}


def get_project_root() -> Path:
    return ROOT_DIR


def load_config(
    config_name: str, *, config_dir: str | Path | None = None
) -> dict[str, Any] | list[dict[str, str]]:
    """Load a config file from JSON, YAML or CSV.

    CSV files are read as a list of dictionaries, while JSON files are parsed as objects.
    """
    target_dir = Path(config_dir) if config_dir is not None else CONFIG_DIR
    config_path = Path(target_dir) / config_name

    if config_path.suffix.lower() == ".json":
        with config_path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    if config_path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("PyYAML is required for YAML config files") from exc
        with config_path.open("r", encoding="utf-8") as fh:
            parsed = yaml.safe_load(fh) or {}
        return parsed

    if config_path.suffix.lower() == ".csv":
        with config_path.open("r", encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    raise ValueError(f"Unsupported config format for {config_name!r}")


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_yaml(path: str | Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyYAML is required for YAML files") from exc
    with Path(path).open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def get_env_var(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


def get_settings() -> dict[str, str]:
    return _read_env()
