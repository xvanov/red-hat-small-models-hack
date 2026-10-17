"""Write the NeMo Gym dataset files for the default RunConfig (prompt v1, verbose tools, reader on):
resources_servers/rentus/data/{train,heldout,example}.jsonl. Each row carries
`responses_create_params` (system prompt + opening turn + tools) and the full `task`, which
/seed_session and /verify read. run_eval.py --via nemo writes per-config files the same way.

    python gym/prepare_nemo_data.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from run_eval import load_tasks, nemo_rows  # noqa: E402


def main():
    from rentus_operator import RunConfig
    cfg = RunConfig()
    out = HERE / "resources_servers" / "rentus" / "data"
    out.mkdir(parents=True, exist_ok=True)
    for split in ("train", "heldout"):
        rows = nemo_rows(load_tasks(split), cfg)
        with open(out / f"{split}.jsonl", "w") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        if split == "heldout":
            with open(out / "example.jsonl", "w") as f:
                for r in rows[:5]:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(split, len(rows))


if __name__ == "__main__":
    main()
