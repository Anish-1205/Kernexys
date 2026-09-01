from __future__ import annotations

import pytest

from runtime_app.classifier import SentimentClassifier


def test_classifier_is_deterministic() -> None:
    classifier = SentimentClassifier("v1")

    first = classifier.predict("A great and excellent result")
    second = classifier.predict("A great and excellent result")

    assert first == second
    assert first.label == "positive"
    assert 0.5 <= first.confidence <= 1.0


def test_v2_has_intentionally_different_weights() -> None:
    text = "reliable and fast"

    assert SentimentClassifier("v1").predict(text).label == "negative"
    assert SentimentClassifier("v2").predict(text).label == "positive"


def test_unknown_artifact_version_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported baked model version"):
        SentimentClassifier("v3")
