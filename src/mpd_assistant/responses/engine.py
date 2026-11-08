"""Templated responses with locale fallback. Templates live in YAML so non-engineers can review them."""

from functools import cache
from pathlib import Path
from string import Template
from typing import Any, Dict

import yaml

TEMPLATE_DIR = Path(__file__).parent / "templates"
DEFAULT_LOCALE = "en"


class TemplateNotFound(KeyError):
    pass


@cache
def _load_locale(locale: str, directory: str = str(TEMPLATE_DIR)) -> Dict[str, str]:
    path = Path(directory) / f"{locale}.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in data.items()}


def render(key: str, locale: str = DEFAULT_LOCALE, variables: Dict[str, Any] | None = None, directory: Path | None = None) -> str:
    base = str(directory or TEMPLATE_DIR)
    raw = _load_locale(locale, base).get(key)
    if raw is None and locale != DEFAULT_LOCALE:
        raw = _load_locale(DEFAULT_LOCALE, base).get(key)
    if raw is None:
        raise TemplateNotFound(key)
    return Template(raw).safe_substitute({k: str(v) for k, v in (variables or {}).items()})
