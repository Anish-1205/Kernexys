"""Small deterministic classifier with versioned, in-image weights."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

_TOKEN_PATTERN = re.compile(r"[a-z']+")

_VERSIONED_WEIGHTS: dict[str, tuple[float, dict[str, float]]] = {
    "v1": (
        -0.2,
        {
            "excellent": 1.8,
            "good": 1.2,
            "great": 1.6,
            "happy": 1.1,
            "love": 1.8,
            "bad": -1.3,
            "hate": -1.8,
            "poor": -1.2,
            "sad": -1.0,
            "terrible": -1.9,
        },
    ),
    "v2": (
        -0.1,
        {
            "excellent": 1.7,
            "fast": 0.8,
            "good": 1.1,
            "great": 1.5,
            "happy": 1.0,
            "love": 1.7,
            "reliable": 1.0,
            "stable": 0.9,
            "bad": -1.2,
            "flaky": -1.2,
            "hate": -1.7,
            "poor": -1.1,
            "sad": -0.9,
            "slow": -0.8,
            "terrible": -1.8,
        },
    ),
}


@dataclass(frozen=True, slots=True)
class Prediction:
    label: str
    confidence: float


class SentimentClassifier:
    def __init__(self, version: str) -> None:
        try:
            self._bias, self._weights = _VERSIONED_WEIGHTS[version]
        except KeyError as exc:
            raise ValueError(f"unsupported baked model version: {version}") from exc
        self.version = version

    def predict(self, text: str) -> Prediction:
        tokens = _TOKEN_PATTERN.findall(text.lower())
        raw_score = self._bias + sum(self._weights.get(token, 0.0) for token in tokens)
        positive_probability = 1.0 / (1.0 + math.exp(-raw_score))
        if positive_probability >= 0.5:
            return Prediction("positive", round(positive_probability, 6))
        return Prediction("negative", round(1.0 - positive_probability, 6))
