"""Configuration loader for QuantLab."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


class Config(BaseModel):
    raw: dict[str, Any] = {}

    def load(self, path: str | Path | None = None) -> "Config":
        if path is None:
            path = _PROJECT_ROOT / "config" / "config.yaml"
        path = Path(path)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                self.raw = yaml.safe_load(f) or {}
        return self

    def get(self, *keys: str, default: Any = None) -> Any:
        current = self.raw
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
                if current is None:
                    return default
            else:
                return default
        return current

    def get_env(self, key: str, default: str = "") -> str:
        return os.getenv(key, default)


config = Config().load()
