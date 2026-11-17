"""Guard backends, built by name. Heavy ones (the LLM judge, the classifier) import lazily."""

from __future__ import annotations

from agentguard.guard.backends.allow_all import AllowAll
from agentguard.guard.backends.rules import RulesBackend
from agentguard.guard.schemas import GuardBackend

BACKEND_NAMES = ("allow_all", "rules", "judge-cheap", "judge-strong", "classifier")


def build_backend(name: str) -> GuardBackend:
    if name == "allow_all":
        return AllowAll()
    if name == "rules":
        return RulesBackend()
    if name.startswith("judge-"):
        from agentguard.guard.backends.llm_judge import LLMJudge

        return LLMJudge.preset(name)
    if name == "classifier":
        from agentguard.guard.backends.classifier import ClassifierBackend

        return ClassifierBackend.load()
    raise ValueError(f"unknown backend {name!r}; choose from {', '.join(BACKEND_NAMES)}")


__all__ = ["BACKEND_NAMES", "AllowAll", "RulesBackend", "build_backend"]
