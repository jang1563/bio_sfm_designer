"""Fine-tune a bio-harm INTENT classification head from microsoft/deberta-v3-base.

The base encoder has no classification head, so the screen needs a trained one. This reads
labeled JSONL ({"text": ..., "label": 0|1}; label 1 = bio-harmful intent) for --train and
--eval, fine-tunes a 2-class sequence-classification head on top of the base, and
save_pretrained()s a model dir that hpc/screen_deberta.py --model <dir> consumes directly. Also
writes metrics.json (accuracy / precision / recall / F1 / AUROC / FPR).

RUNS ON CAYUGA/EXPANSE (GPU; needs torch + transformers + sklearn). The repo ships no labeled
data — bring your own. Produces the head; the screen then scores intents with it.
"""

from __future__ import annotations

import argparse
import json
import sys


def _load(path):
    with open(path) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    return [str(r["text"]) for r in rows], [int(r["label"]) for r in rows]


def main() -> None:
    ap = argparse.ArgumentParser(description="fine-tune a bio-harm intent head from deberta-v3-base")
    ap.add_argument("--base", default="microsoft/deberta-v3-base")
    ap.add_argument("--train", required=True, help="JSONL {text,label}; label 1 = harmful intent")
    ap.add_argument("--eval", required=True, help="JSONL {text,label}")
    ap.add_argument("--out", required=True, help="output model dir (consumed by screen_deberta.py --model)")
    ap.add_argument("--epochs", type=float, default=5.0)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--max-length", type=int, default=512)
    args = ap.parse_args()

    import numpy as np
    import torch
    from sklearn.metrics import accuracy_score, precision_recall_fscore_support, roc_auc_score
    from transformers import (AutoModelForSequenceClassification, AutoTokenizer,
                              Trainer, TrainingArguments)

    tok = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForSequenceClassification.from_pretrained(args.base, num_labels=2)

    tr_text, tr_lab = _load(args.train)
    ev_text, ev_lab = _load(args.eval)

    class DS(torch.utils.data.Dataset):
        def __init__(self, texts, labels):
            self.enc = tok(texts, truncation=True, max_length=args.max_length, padding=True)
            self.labels = labels

        def __len__(self):
            return len(self.labels)

        def __getitem__(self, i):
            item = {k: torch.tensor(v[i]) for k, v in self.enc.items()}
            item["labels"] = torch.tensor(self.labels[i])
            return item

    # Train without per-epoch eval (avoids the eval_strategy/evaluation_strategy version split);
    # evaluate once at the end.
    targs = TrainingArguments(
        output_dir=args.out + "/_ckpt", num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch, per_device_eval_batch_size=args.batch,
        learning_rate=args.lr, logging_steps=20, save_strategy="no", report_to=[],
    )
    trainer = Trainer(model=model, args=targs, train_dataset=DS(tr_text, tr_lab))
    trainer.train()

    pred = trainer.predict(DS(ev_text, ev_lab))
    probs = torch.softmax(torch.tensor(pred.predictions), dim=-1).numpy()
    preds = probs.argmax(-1)
    labels = np.array(ev_lab)
    pr, rc, f1, _ = precision_recall_fscore_support(labels, preds, average="binary", zero_division=0)
    try:
        auroc = float(roc_auc_score(labels, probs[:, 1]))
    except Exception:
        auroc = None
    neg = labels == 0
    fpr = float((preds[neg] == 1).mean()) if neg.any() else None
    metrics = {"accuracy": float(accuracy_score(labels, preds)), "precision": float(pr),
               "recall": float(rc), "f1": float(f1), "auroc": auroc, "fpr": fpr}

    model.save_pretrained(args.out)
    tok.save_pretrained(args.out)
    with open(args.out + "/metrics.json", "w") as fh:
        json.dump({"base": args.base, "n_train": len(tr_lab), "n_eval": len(ev_lab),
                   "epochs": args.epochs, "eval": metrics}, fh, indent=2, sort_keys=True)
    print(f"saved head -> {args.out}", file=sys.stderr)
    print(json.dumps(metrics, indent=2), file=sys.stderr)


if __name__ == "__main__":
    main()
