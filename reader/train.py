"""Full-parameter SFT of the reader with TRL.

Input  : data/processed/reader/{train,dev}.jsonl (falls back to data/published/reader)
Format : prompt = the model's chat template over (SYSTEM_PROMPT, user message) from
         reader/prompt.py, rendered with thinking disabled; completion = the canonical
         reader JSON + end-of-turn token. Loss on the completion only.
Stop   : eval loss on a dev subset every --eval-steps, early stopping (patience 3),
         best checkpoint restored at the end.
Output : a plain, merged HF checkpoint at --out (full fine-tune, so there is no adapter
         to merge), servable by vLLM as is. The saved chat template defaults to
         thinking off, so callers need no chat_template_kwargs.

Usage (on the GPU box, inside reader/.venv-train):
  python reader/train.py --model Qwen/Qwen3-0.6B --out reader/checkpoints/rentus-reader
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from prompt import build_messages, target_text  # noqa: E402
from eval import load_rows  # noqa: E402

NO_THINK_PREFIX = "{%- if enable_thinking is not defined %}{%- set enable_thinking = false %}{%- endif %}"


def to_examples(rows, tok):
    out = []
    for r in rows:
        prompt = tok.apply_chat_template(build_messages(r["input"]), tokenize=False, add_generation_prompt=True,
                                         enable_thinking=False)
        out.append({"prompt": prompt, "completion": target_text(r["output"]) + tok.eos_token})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3-0.6B")
    ap.add_argument("--out", default=str(HERE / "checkpoints" / "rentus-reader"))
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=3e-5)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--max-length", type=int, default=1536)
    ap.add_argument("--eval-steps", type=int, default=100)
    ap.add_argument("--dev-subset", type=int, default=400, help="dev rows used for eval loss (0 = all)")
    ap.add_argument("--limit-train", type=int, default=0)
    ap.add_argument("--grad-checkpointing", action="store_true")
    ap.add_argument("--seed", type=int, default=17)
    a = ap.parse_args()

    import torch
    from datasets import Dataset
    from transformers import AutoModelForCausalLM, AutoTokenizer, EarlyStoppingCallback
    from trl import SFTConfig, SFTTrainer

    tok = AutoTokenizer.from_pretrained(a.model)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    train_rows = load_rows("train")
    if a.limit_train:
        train_rows = train_rows[:a.limit_train]
    dev_rows = load_rows("dev")
    if a.dev_subset:
        dev_rows = dev_rows[:a.dev_subset]
    train_ds = Dataset.from_list(to_examples(train_rows, tok)).shuffle(seed=a.seed)
    dev_ds = Dataset.from_list(to_examples(dev_rows, tok))
    print(f"train {len(train_ds)}  dev {len(dev_ds)}  eos={tok.eos_token!r}")
    print("sample prompt tail:", train_ds[0]["prompt"][-200:].replace("\n", "\\n"))
    print("sample completion:", train_ds[0]["completion"])

    model = AutoModelForCausalLM.from_pretrained(a.model, dtype=torch.bfloat16, attn_implementation="sdpa")
    ckpt_dir = Path(a.out).parent / (Path(a.out).name + "-trainer")
    cfg = SFTConfig(
        output_dir=str(ckpt_dir),
        num_train_epochs=a.epochs,
        learning_rate=a.lr,
        lr_scheduler_type="cosine",
        warmup_steps=20,
        weight_decay=0.0,
        per_device_train_batch_size=a.batch,
        per_device_eval_batch_size=a.batch * 2,
        gradient_accumulation_steps=a.grad_accum,
        gradient_checkpointing=a.grad_checkpointing,
        bf16=True,
        max_length=a.max_length,
        completion_only_loss=True,
        eos_token=tok.eos_token,
        eval_strategy="steps",
        eval_steps=a.eval_steps,
        save_strategy="steps",
        save_steps=a.eval_steps,
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        logging_steps=10,
        report_to="none",
        seed=a.seed,
        dataloader_num_workers=2,
    )
    trainer = SFTTrainer(model=model, args=cfg, train_dataset=train_ds, eval_dataset=dev_ds, processing_class=tok,
                         callbacks=[EarlyStoppingCallback(early_stopping_patience=3)])
    t0 = time.time()
    trainer.train()
    train_s = time.time() - t0
    final = trainer.evaluate()

    out = Path(a.out)
    trainer.save_model(str(out))
    tok.save_pretrained(str(out))
    # thinking off by default in the served chat template
    cfg_path = out / "tokenizer_config.json"
    tpl_file = out / "chat_template.jinja"
    if tpl_file.exists():
        t = tpl_file.read_text()
        if not t.startswith(NO_THINK_PREFIX):
            tpl_file.write_text(NO_THINK_PREFIX + t)
    elif cfg_path.exists():
        tc = json.loads(cfg_path.read_text())
        if isinstance(tc.get("chat_template"), str) and not tc["chat_template"].startswith(NO_THINK_PREFIX):
            tc["chat_template"] = NO_THINK_PREFIX + tc["chat_template"]
            cfg_path.write_text(json.dumps(tc, indent=2, ensure_ascii=False))
    info = {"base_model": a.model, "train_rows": len(train_ds), "dev_rows_for_loss": len(dev_ds),
            "epochs_max": a.epochs, "lr": a.lr, "effective_batch": a.batch * a.grad_accum,
            "global_steps": trainer.state.global_step, "best_checkpoint": trainer.state.best_model_checkpoint,
            "best_eval_loss": trainer.state.best_metric, "final_eval": final, "train_seconds": round(train_s, 1),
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "log_history": trainer.state.log_history}
    (out / "rentus_train_info.json").write_text(json.dumps(info, indent=1))
    print(json.dumps({k: v for k, v in info.items() if k != "log_history"}, indent=1))


if __name__ == "__main__":
    main()
