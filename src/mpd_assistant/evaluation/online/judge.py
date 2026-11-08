"""Sampled LLM judge: is the answer supported by the evidence it was given? Fails soft: no verdict means no change."""

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import List

from mpd_assistant.agents.common import parse_json_object
from mpd_assistant.agents.prompts import load_prompt
from mpd_assistant.core.llm.client import LLM, LLMError
from mpd_assistant.observability.metrics import JUDGE_VERDICTS

SYSTEM = load_prompt("evaluator", "judge").render()

MAX_CHARS = 3000


@dataclass
class JudgeResult:
    supported: float
    issues: List[str] = field(default_factory=list)
    judged: bool = True


class LlmJudge:
    def __init__(self, llm: LLM, sample_rate: float = 0.2, threshold: float = 0.6, rng: Callable[[], float] = random.random):
        self._llm, self._rate, self._threshold, self._rng = llm, sample_rate, threshold, rng

    def should_judge(self) -> bool:
        return self._rng() < self._rate

    async def review(self, answer: str, evidence: str) -> JudgeResult:
        """Returns judged=False when the model failed or answered unparseably, so callers leave the reply alone."""
        try:
            result = await self._llm.complete(
                [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"EVIDENCE:\n{evidence[:MAX_CHARS]}\n\nANSWER:\n{answer[:MAX_CHARS]}"},
                ],
                tier="mid",  # a wrong verdict replaces a good answer, and only a fraction of turns are judged, so the stronger model is worth it
                max_tokens=150,
                temperature=0.0,
            )
        except LLMError:
            JUDGE_VERDICTS.labels("error").inc()
            return JudgeResult(1.0, judged=False)
        parsed = parse_json_object(result.text) or {}
        try:
            score = max(0.0, min(1.0, float(parsed["supported"])))
        except (KeyError, TypeError, ValueError):
            JUDGE_VERDICTS.labels("unparseable").inc()
            return JudgeResult(1.0, judged=False)
        issues = [str(i)[:120] for i in parsed.get("issues", []) if isinstance(i, str | int | float)][:3] if isinstance(parsed.get("issues"), list) else []
        JUDGE_VERDICTS.labels("supported" if score >= self._threshold else "unsupported").inc()
        return JudgeResult(score, issues)

    @property
    def threshold(self) -> float:
        return self._threshold
