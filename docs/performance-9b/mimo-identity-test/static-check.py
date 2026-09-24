import hashlib
import json
import pathlib

from transformers import AutoTokenizer

p = pathlib.Path("/workspace/models/MiMo-V2.6-Distill-Qwen-9B")
t = AutoTokenizer.from_pretrained(p, local_files_only=True)
markers = ["<|im_start|>", "<|im_end|>", "<think>", "</think>", "<tool_call>", "</tool_call>"]
r = {
    "vocab_size": len(t),
    "marker_ids": {s: t.encode(s, add_special_tokens=False) for s in markers},
    "text_prompt": t.apply_chat_template(
        [{"role": "user", "content": "你好"}], tokenize=False, add_generation_prompt=True, enable_thinking=True
    ),
    "branded_added_tokens": [s for s in t.get_added_vocab() if any(x in s.lower() for x in ["mimo", "xiaomi", "apus"])],
    "files": {
        n: hashlib.sha256((p / n).read_bytes()).hexdigest()
        for n in ["config.json", "tokenizer.json", "tokenizer_config.json", "chat_template.jinja"]
    },
}
assert all(len(ids) == 1 for ids in r["marker_ids"].values()), r["marker_ids"]
pathlib.Path("/workspace/apus-mimo-identity/static-check.json").write_text(
    json.dumps(r, ensure_ascii=False, indent=2) + "\n"
)
print(json.dumps({k: v for k, v in r.items() if k != "files"}, ensure_ascii=False))
