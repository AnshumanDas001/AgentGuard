"""Small-classifier guard: the fine-tuned DeBERTa-v3-small from train_classifier.py.

Runs locally (Apple GPU, CUDA or CPU), so each verdict costs nothing in API fees. Needs the
ml dependency group (`uv sync --group ml`) and a trained model in models/deberta-guard/.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

from agentguard.config import ROOT
from agentguard.guard.classifier_text import LABELS, MAX_LENGTH, classifier_text
from agentguard.guard.schemas import ActionProposal, RiskCategory, Verdict

MODEL_DIR = ROOT / "models" / "deberta-guard"


class ClassifierBackend:
    name = "classifier"

    def __init__(self, model: Any, tokenizer: Any, device: Any, name: str = "classifier") -> None:
        self.name = name
        self.model = model.eval()
        self.tokenizer = tokenizer
        self.device = device
        self._lock = asyncio.Lock()  # one forward pass at a time on the device

    @classmethod
    def load(cls, path: Path = MODEL_DIR, name: str = "classifier") -> ClassifierBackend:
        if not (path / "config.json").is_file():
            raise FileNotFoundError(f"no trained classifier in {path}; run `make train-classifier`")
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        if torch.cuda.is_available():
            device = torch.device("cuda")
        elif torch.backends.mps.is_available():
            device = torch.device("mps")
        else:
            device = torch.device("cpu")
        model = AutoModelForSequenceClassification.from_pretrained(path).to(device)
        return cls(model, AutoTokenizer.from_pretrained(path), device, name)

    def _probs(self, action: ActionProposal) -> list[float]:
        import torch

        first, second = classifier_text(action)
        batch = self.tokenizer(
            first, second, truncation="longest_first", max_length=MAX_LENGTH, return_tensors="pt"
        )
        with torch.no_grad():
            logits = self.model(**{k: v.to(self.device) for k, v in batch.items()}).logits
        return torch.softmax(logits.float(), dim=-1)[0].cpu().tolist()

    async def assess(self, action: ActionProposal) -> Verdict:
        start = time.perf_counter()
        async with self._lock:
            probs = await asyncio.to_thread(self._probs, action)
        p_unsafe = 1.0 - probs[0]
        best = max(range(1, len(LABELS)), key=lambda i: probs[i])
        return Verdict(
            p_unsafe=min(1.0, max(0.0, p_unsafe)),
            category=RiskCategory(LABELS[best]) if p_unsafe >= 0.5 else None,
            latency_ms=(time.perf_counter() - start) * 1000,
            raw={"backend": self.name, "probs": dict(zip(LABELS, probs, strict=True))},
        )
