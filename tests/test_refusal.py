"""Offline tests for the eval's refusal detector. No API keys, no network: the
config and generation modules are stubbed before eval/run_eval.py is loaded.

Run from the repo root:  PYTHONPATH=backend uv run --with pytest pytest tests/ -q
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def run_eval(monkeypatch):
    config = ModuleType("app.config")
    config.settings = SimpleNamespace(anthropic_api_key="offline")
    generate = ModuleType("app.generation.generate")
    generate.MODEL, generate.Answer, generate.answer = "stub", object, None
    monkeypatch.setitem(sys.modules, "app.config", config)
    monkeypatch.setitem(sys.modules, "app.generation.generate", generate)
    spec = importlib.util.spec_from_file_location("run_eval", ROOT / "eval" / "run_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cited(text: str, n: int = 3) -> SimpleNamespace:
    return SimpleNamespace(text=text, citations=[object()] * n)


def test_hedge_after_a_citation_is_still_an_answer(run_eval):
    # The faith-is-feeling answer from the Opus 5.5 run: a full answer whose
    # trailing parenthetical hedge used to trip the decline regex.
    text = (
        "In Chapter 4, Goddard defines faith simply as **feeling**. He reads the "
        "line as a statement about feeling [1]. (The passages provided don't say "
        "whether this is the book's final chapter.)"
    )
    assert not run_eval.refused(cited(text))


@pytest.mark.parametrize("opening", [
    "The book doesn't say anything about diet [1].",
    "The passages provided don't answer this. They don't mention where he was born [1].",
    "These passages don't address stock market investing [1].",
    "The book's passages don't mention astrology [1].",
])
def test_decline_before_the_first_citation_is_a_refusal(run_eval, opening):
    assert run_eval.refused(cited(opening))


def test_answer_without_citations_is_a_refusal(run_eval):
    assert run_eval.refused(cited("Feeling is the secret.", n=0))
