"""Fine-tune DeBERTa-v3-small on the train split; pick the epoch with the best dev AUROC.

    make train-classifier

The model has 8 outputs (safe + the 7 categories). Its p_unsafe is 1 - P(safe), and its
category is the most likely unsafe class. Rare classes get larger loss weights. Weights are
saved to models/deberta-guard/ (gitignored: about 550 MB); metrics.json next to them records
the settings and each epoch's dev results, and is copied to results/classifier/.
The test split is never read here.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")  # a few ops lack Apple-GPU kernels

import torch  # noqa: E402
from transformers import (  # noqa: E402
    AutoModelForSequenceClassification,
    AutoTokenizer,
    get_linear_schedule_with_warmup,
)

from agentguard.config import RESULTS_DIR, ROOT  # noqa: E402
from agentguard.eval.run import auroc, load_split, proposal  # noqa: E402
from agentguard.guard.classifier_text import LABELS, MAX_LENGTH, classifier_text  # noqa: E402

BASE_MODEL = "microsoft/deberta-v3-small"
MODEL_DIR = ROOT / "models" / "deberta-guard"


def device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def target(row: dict[str, Any]) -> int:
    return 0 if row["label"] == "safe" else LABELS.index(row["category"])


def encode(tokenizer: Any, rows: list[dict[str, Any]]) -> dict[str, torch.Tensor]:
    pairs = [classifier_text(proposal(r)) for r in rows]
    return tokenizer(
        [a for a, _ in pairs],
        [b for _, b in pairs],
        truncation="longest_first",
        max_length=MAX_LENGTH,
        padding=True,
        return_tensors="pt",
    )


@torch.no_grad()
def predict(
    model: Any, tokenizer: Any, rows: list[dict[str, Any]], dev: torch.device, batch_size: int = 4
) -> list[list[float]]:
    model.eval()
    probs: list[list[float]] = []
    for i in range(0, len(rows), batch_size):
        batch = {k: v.to(dev) for k, v in encode(tokenizer, rows[i : i + batch_size]).items()}
        probs.extend(torch.softmax(model(**batch).logits.float(), dim=-1).cpu().tolist())
    return probs


def dev_metrics(rows: list[dict[str, Any]], probs: list[list[float]]) -> dict[str, Any]:
    p_unsafe = [1.0 - p[0] for p in probs]
    pos = [p for p, r in zip(p_unsafe, rows, strict=True) if r["label"] == "unsafe"]
    neg = [p for p, r in zip(p_unsafe, rows, strict=True) if r["label"] == "safe"]
    caught = [
        (r, p)
        for r, p in zip(rows, probs, strict=True)
        if r["label"] == "unsafe" and 1.0 - p[0] >= 0.5
    ]
    category_right = sum(
        LABELS[1 + max(range(7), key=lambda k: p[1 + k])] == r["category"] for r, p in caught
    )
    return {
        "auroc": round(auroc(pos, neg) or 0.0, 4),
        "recall@0.5": round(sum(p >= 0.5 for p in pos) / len(pos), 4),
        "false_positive_rate@0.5": round(sum(p >= 0.5 for p in neg) / len(neg), 4),
        "category_correct_when_caught": round(category_right / len(caught), 4) if caught else None,
    }


def train(
    epochs: int, lr: float, batch_size: int, seed: int, out: Path, accumulate: int = 4
) -> dict[str, Any]:
    random.seed(seed)
    torch.manual_seed(seed)
    dev = device()
    train_rows, dev_rows = load_split("train"), load_split("dev")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL,
        num_labels=len(LABELS),
        id2label=dict(enumerate(LABELS)),
        label2id={name: i for i, name in enumerate(LABELS)},
        dtype=torch.float32,  # the checkpoint is stored in float16; training in it overflows
    ).to(dev)

    # Inverse-square-root class weights: rare categories count more, but not wildly more.
    counts = Counter(target(r) for r in train_rows)
    weights = torch.tensor(
        [1.0 / math.sqrt(counts.get(i, 1)) for i in range(len(LABELS))], dtype=torch.float
    )
    weights = (weights / weights.mean()).to(dev)
    loss_fn = torch.nn.CrossEntropyLoss(weight=weights)

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    micro = max(1, batch_size // accumulate)  # rows in memory at once
    steps = epochs * math.ceil(len(train_rows) / batch_size)
    scheduler = get_linear_schedule_with_warmup(optimizer, int(0.1 * steps), steps)

    history: list[dict[str, Any]] = []
    best_auroc = -1.0
    started = time.time()
    for epoch in range(1, epochs + 1):
        model.train()
        order = list(range(len(train_rows)))
        random.shuffle(order)
        total = 0.0
        for i in range(0, len(order), batch_size):
            batch_rows = [train_rows[j] for j in order[i : i + batch_size]]
            # Gradient accumulation: run the batch in small pieces, add up the gradients,
            # then take one optimizer step, so only `micro` rows sit in memory at a time.
            for k in range(0, len(batch_rows), micro):
                piece = batch_rows[k : k + micro]
                inputs = {key: v.to(dev) for key, v in encode(tokenizer, piece).items()}
                labels = torch.tensor([target(r) for r in piece], device=dev)
                loss = loss_fn(model(**inputs).logits.float(), labels)
                if not torch.isfinite(loss):
                    raise FloatingPointError(f"loss became {loss.item()} in epoch {epoch}")
                (loss * len(piece) / len(batch_rows)).backward()
                total += loss.item() * len(piece)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()
        if dev.type == "mps":
            torch.mps.empty_cache()
        metrics = dev_metrics(dev_rows, predict(model, tokenizer, dev_rows, dev))
        record = {
            "epoch": epoch,
            "train_loss": round(total / len(train_rows), 4),
            "dev": metrics,
            "minutes": round((time.time() - started) / 60, 1),
        }
        history.append(record)
        print(json.dumps(record), flush=True)
        if metrics["auroc"] > best_auroc:
            best_auroc = metrics["auroc"]
            out.mkdir(parents=True, exist_ok=True)
            model.save_pretrained(out)
            tokenizer.save_pretrained(out)

    best = max(history, key=lambda h: h["dev"]["auroc"])
    report = {
        "base_model": BASE_MODEL,
        "device": str(dev),
        "settings": {
            "epochs": epochs,
            "lr": lr,
            "batch_size": batch_size,
            "seed": seed,
            "accumulate": accumulate,
            "dtype": "float32",
            "max_length": MAX_LENGTH,
            "class_weights": "1/sqrt(count), mean 1",
        },
        "train_rows": len(train_rows),
        "dev_rows": len(dev_rows),
        "labels": LABELS,
        "epochs": history,
        "best_epoch": best["epoch"],
        "best_dev": best["dev"],
    }
    (out / "metrics.json").write_text(json.dumps(report, indent=2) + "\n")
    (RESULTS_DIR / "classifier").mkdir(parents=True, exist_ok=True)
    shutil.copy(out / "metrics.json", RESULTS_DIR / "classifier" / "metrics.json")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentguard.guard.train_classifier")
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--lr", type=float, default=3e-5)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--accumulate", type=int, default=4, help="split each batch into this many pieces"
    )
    parser.add_argument("--out", type=Path, default=MODEL_DIR)
    args = parser.parse_args(argv)
    report = train(args.epochs, args.lr, args.batch_size, args.seed, args.out, args.accumulate)
    print(json.dumps({"best_epoch": report["best_epoch"], "best_dev": report["best_dev"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
