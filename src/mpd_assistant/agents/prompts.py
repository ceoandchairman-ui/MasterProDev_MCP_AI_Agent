"""Prompt registry: every agent prompt lives in a versioned YAML file next to the agent, validated when it loads.

A prompt file has a `version` and a `text`. The text uses str.format placeholders ({language}); literal braces are doubled
({{ and }}), exactly as in a Python format string. Loading fails fast on a missing version, empty text or malformed
braces, so a bad prompt stops the app at startup rather than failing on a user's turn. The combined version of all
prompts goes into cache keys, so changing any prompt makes old cached answers miss.
"""

import hashlib
import string
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Dict, FrozenSet

import yaml

AGENTS_DIR = Path(__file__).parent


class PromptError(ValueError):
    pass


@dataclass(frozen=True)
class Prompt:
    agent: str
    name: str
    version: str
    text: str
    variables: FrozenSet[str]

    def render(self, **values: object) -> str:
        missing = self.variables - set(values)
        if missing:
            raise PromptError(f"{self.agent}/{self.name} needs values for: {', '.join(sorted(missing))}")
        return self.text.format(**values)


def _variables(text: str) -> FrozenSet[str]:
    try:
        return frozenset(field for _, field, _, _ in string.Formatter().parse(text) if field)
    except ValueError as exc:
        raise PromptError(f"malformed braces in prompt: {exc}") from exc


@cache
def load_prompt(agent: str, name: str, directory: str = str(AGENTS_DIR)) -> Prompt:
    path = Path(directory) / agent / "prompts" / f"{name}.yaml"
    if not path.exists():
        raise PromptError(f"prompt file not found: {agent}/prompts/{name}.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    version, text = str(data.get("version", "")).strip(), str(data.get("text", "")).strip()
    if not version:
        raise PromptError(f"{agent}/{name}: missing version")
    if not text:
        raise PromptError(f"{agent}/{name}: empty text")
    return Prompt(agent, name, version, text, _variables(text))


def prompt_versions(directory: Path = AGENTS_DIR) -> Dict[str, str]:
    """Every prompt on disk, as {"agent/name": version}. Used for traces and cache keys."""
    out: Dict[str, str] = {}
    for path in sorted(Path(directory).glob("*/prompts/*.yaml")):
        prompt = load_prompt(path.parent.parent.name, path.stem, str(directory))
        out[f"{prompt.agent}/{prompt.name}"] = prompt.version
    return out


def prompt_set_version(directory: Path = AGENTS_DIR) -> str:
    """Short digest of all prompt texts and versions: changes whenever any prompt changes."""
    parts = []
    for path in sorted(Path(directory).glob("*/prompts/*.yaml")):
        prompt = load_prompt(path.parent.parent.name, path.stem, str(directory))
        parts.append(f"{prompt.agent}/{prompt.name}:{prompt.version}:{prompt.text}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:8]


__all__ = ["Prompt", "PromptError", "load_prompt", "prompt_set_version", "prompt_versions"]
