"""Build a small, traceable OPD candidate pool; never assert benchmark cleanliness."""

import argparse
import collections
import hashlib
import json
import re
import unicodedata
from pathlib import Path

import jinja2
import pyarrow as pa
import pyarrow.parquet as pq
from tokenizers import Tokenizer

REV = "96e88d579cb1ee68c9183c52e5d133f58cf370bf"
CHAT_REV = "9f36020daf067f1a8b39336bf619fe30af30bb02"
RULES = {
    "keywords:existence",
    "keywords:forbidden_words",
    "length_constraints:number_words",
    "detectable_format:json_format",
    "change_case:english_lowercase",
    "change_case:english_uppercase",
    "startend:end_checker",
}
# Manually reviewed standalone chat requests; broad general domain, not a benchmark.
CHAT_ROWS = [
    2,
    5,
    8,
    12,
    15,
    20,
    26,
    27,
    34,
    37,
    40,
    41,
    43,
    46,
    52,
    55,
    57,
    59,
    71,
    77,
    86,
    96,
    100,
    105,
    109,
    129,
    138,
    141,
    157,
    204,
    239,
    112,
    163,
    167,
    175,
    178,
    187,
    188,
    224,
    234,
]


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def norm(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--chat", type=Path, required=True)
    ap.add_argument("--tokenizer", type=Path, required=True)
    ap.add_argument("--mbpp", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    tok = Tokenizer.from_file(str(args.tokenizer / "tokenizer.json"))
    config = json.loads((args.tokenizer / "tokenizer_config.json").read_text())
    env = jinja2.Environment()
    env.globals["raise_exception"] = lambda s: (_ for _ in ()).throw(ValueError(s))
    template = env.from_string(config["chat_template"])
    pools = collections.defaultdict(list)
    rejected = collections.Counter()
    seen = set()

    def add(domain, messages, reference, source, revision, file, row, metadata):
        messages = [m for m in messages if m["content"] and m["role"] != "assistant"]
        text = "\n".join(m["content"] for m in messages)
        if not messages or messages[-1]["role"] != "user":
            rejected["invalid_roles"] += 1
            return
        if re.search(r"\[MASKED\]|\[REDACTED\]|NAME_\d|\[PLACEHOLDER\]", text):
            rejected["placeholder"] += 1
            return
        if re.search(
            r"\b(GPQA|MMLU|SWE-bench|HumanEval|MBPP|AIME|AMC|GSM8K|IFEval|IFBench|Terminal.Bench)\b", text, re.I
        ):
            rejected["benchmark_mention"] += 1
            return
        h = digest(norm(text))
        if h in seen:
            rejected["duplicate"] += 1
            return
        rendered = template.render(messages=messages, add_generation_prompt=True, enable_thinking=False, tools=None)
        count = len(tok.encode(rendered, add_special_tokens=False).ids)
        if count > 1024:
            rejected["prompt_over_1024"] += 1
            return
        seen.add(h)
        extra = {
            "domain": domain,
            "source_repo": source,
            "source_revision": revision,
            "source_file": file,
            "source_row": row,
            "sample_id": f"{domain}-{h[:20]}",
            "prompt_sha256": h,
            "prompt_tokens": count,
            "metadata_json": json.dumps(metadata, ensure_ascii=False),
            "instruction_id_list": metadata.get("instruction_id_list", []),
            "kwargs_json": json.dumps(metadata.get("kwargs", [])),
            "verification_status": "candidate_not_independently_verified",
            "license": metadata.get("license", "apache-2.0 declared by archive; upstream audit pending"),
        }
        pools[domain].append(
            {
                "data_source": domain,
                "ability": domain,
                "prompt": messages,
                "reward_model": {"style": "rule", "ground_truth": reference},
                "extra_info": extra,
            }
        )

    files = {
        "math": "DeepMath-103K/train_filtered_level6.parquet",
        "instruction": "IF/train.parquet",
        "knowledge_mcqa": "Science/train.parquet",
    }
    for domain, rel in files.items():
        row = -1
        for batch in pq.ParquetFile(args.source / rel).iter_batches(batch_size=64):
            for x in batch.to_pylist():
                row += 1
                if len(pools[domain]) >= 40:
                    break
                e = x["extra_info"]
                gt = x["reward_model"]["ground_truth"]
                text = "\n".join(m["content"] for m in x["prompt"])
                if domain == "math" and not re.fullmatch(r"-?\d+(?:\.\d+)?", gt.strip()):
                    continue
                if domain == "instruction":
                    ids, kwargs = e.get("instruction_id_list"), e.get("kwargs")
                    if (
                        not ids
                        or not set(ids) <= RULES
                        or not kwargs
                        or len(ids) != len(kwargs)
                        or not all(isinstance(k, dict) for k in kwargs)
                    ):
                        continue
                    e = dict(e, kwargs=[{k: v for k, v in d.items() if v is not None} for d in kwargs])
                if domain == "knowledge_mcqa":
                    if row in {108, 228}:
                        # Suspect Calvin-cycle premise / missing referenced curve.
                        continue
                    if not re.search(
                        r"\b(molecule|enzyme|electron|photosynthesis|mitochondria|magnetic|thermodynamic|chemical|quantum|protein|voltage|wavelength)\b",
                        text,
                        re.I,
                    ):
                        continue
                    if re.search(
                        r"\b(court|contract|plaintiff|defendant|lawsuit|crime|legal|company|"
                        r"corporation|tax|statute|state imposes)\b",
                        text,
                        re.I,
                    ):
                        continue
                    if gt != e.get("correct_letter") or gt not in e.get("valid_letters", []):
                        continue
                add(domain, x["prompt"], gt, "icemoon28/MOPD-Training-Data", REV, rel, row, e)
            if len(pools[domain]) >= 40:
                break

    for i, x in enumerate(pq.read_table(args.mbpp).to_pylist()):
        if len(pools["code"]) >= 40:
            break
        # Show an interface example, not reference implementation or its output.
        first_test = x["test_list"][0]
        call = first_test.removeprefix("assert ").split(" == ")[0]
        prompt = (
            x["prompt"]
            + "\nUse the function interface illustrated by this call: "
            + call
            + ".\nReturn Python code in a fenced code block."
        )
        add(
            "code",
            [{"role": "user", "content": prompt}],
            json.dumps({"test_list": x["test_list"], "test_imports": x["test_imports"]}),
            "google-research-datasets/mbpp",
            "4bb6404fdc6cacfda99d4ac4205087b89d32030c",
            "sanitized/train-00000-of-00001.parquet",
            i,
            {
                "task_id": x["task_id"],
                "source_split": "train",
                "license": "cc-by-4.0",
                "verifier": "syntax_only",
                "tests_status": "not_executed",
            },
        )

    for i, line in enumerate(args.chat.read_text().splitlines()):
        if i not in CHAT_ROWS:
            continue
        x = json.loads(line)
        m = x["messages"]
        if sum(z["role"] == "user" for z in m) != 1:
            rejected["chat_not_single_turn"] += 1
            continue
        add(
            "chat",
            [z for z in m if z["role"] in {"system", "user"}],
            "",
            "nvidia/Nemotron-Cascade-2-SFT-Data",
            CHAT_REV,
            "chat/chat_part_1.jsonl",
            i,
            {
                "source": x.get("source"),
                "generator": x.get("generator"),
                "verifier": "unscored",
                "license": "nvidia-open-model-license",
            },
        )

    train, val = [], []
    for domain, rows in pools.items():
        # Hash-order split, never by alternate completions of the same task.
        rows.sort(key=lambda x: digest("20260924:" + x["extra_info"]["prompt_sha256"]))
        assert len(rows) == 40, (domain, len(rows))
        for i, row in enumerate(rows):
            split = "val" if i < 8 else "train"
            row["extra_info"]["split"] = split
            (val if split == "val" else train).append(row)
    assert len(train) == 160 and len(val) == 40
    assert not {x["extra_info"]["prompt_sha256"] for x in train} & {x["extra_info"]["prompt_sha256"] for x in val}
    args.out.mkdir(parents=True, exist_ok=True)
    for split, rows in (("train", train), ("val", val)):
        pq.write_table(pa.Table.from_pylist(rows), args.out / f"{split}.parquet")
        (args.out / f"{split}.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows))
    manifest = {
        "status": "candidate_pilot_not_production_quality",
        "seed": 20260924,
        "counts": {d: {"train": 32, "val": 8} for d in pools},
        "rejections": dict(rejected),
        "prompt_token_cap": 1024,
        "thinking": False,
        "tokenizer_sha256": hashlib.sha256((args.tokenizer / "tokenizer.json").read_bytes()).hexdigest(),
        "chat_template_sha256": digest(config["chat_template"]),
        "limitations": [
            "Only exact normalized prompt dedup; near-duplicate and external benchmark corpus checks pending.",
            "Benchmark name exclusion is not a contamination guarantee. DeepMath tasks may overlap public benchmarks; "
            "MBPP uses explicitly official sanitized train only.",
            "Code uses MBPP sanitized train, tests not executed; syntax diagnostic only.",
            "Knowledge MCQA natural-science keyword screened, answer truth not independently verified; not GPQA.",
            "IF tests check format only, not helpfulness. Chat is unscored, not zero ability.",
            "Third-party archive declares Apache-2.0; underlying source license audit not complete.",
            "Small head sample selection is not representative of full source diversity; not a capability leaderboard.",
        ],
        "mbpp_train_sha256": hashlib.sha256(args.mbpp.read_bytes()).hexdigest(),
        "chat_head_sha256": hashlib.sha256(args.chat.read_bytes()).hexdigest(),
        "manual_review": [
            "Chat selected IDs: standalone prompts reviewed; no answer-quality or factuality certification.",
            "Science selected topic excerpts reviewed; rejected row108 suspect Calvin premise and row228 "
            "missing curve reference; answers not independently proven.",
        ],
        "source_files": {rel: hashlib.sha256((args.source / rel).read_bytes()).hexdigest() for rel in files.values()},
        "artifacts": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in args.out.glob("*.parquet")},
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
