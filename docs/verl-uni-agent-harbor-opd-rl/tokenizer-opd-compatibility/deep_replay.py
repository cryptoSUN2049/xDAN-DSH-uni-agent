"""Replay saved rollout text; explicitly not an exact historical tensor reconstruction."""

import argparse
import gc
import hashlib
import json
from pathlib import Path

ROOT = Path("/workspace/verl-uni-agent-harbor-opd-rl")
STUDENT = "/workspace/models/Qwen3.5-9B"
TEACHER = "/workspace/models/Qwen3.8-27B"


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "hf", "vllm", "compare"])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    if args.mode == "prepare":
        from transformers import AutoTokenizer

        student = AutoTokenizer.from_pretrained(STUDENT, local_files_only=True)
        teacher = AutoTokenizer.from_pretrained(TEACHER, local_files_only=True)
        lookup = {}
        for line in (ROOT / "data-overnight-opd-20260924-v2/train.jsonl").read_text().splitlines():
            row = json.loads(line)
            rendered = "".join(m["role"] + "\n" + m["content"] + "\n" for m in row["prompt"])
            lookup[rendered + "assistant\n<think>\n\n</think>\n\n"] = row
        selected = {}
        for step in range(1, 5):
            path = ROOT / f"runs/overnight-opd-20260924-attempt2/rollouts/{step}.jsonl"
            for line in path.read_text().splitlines():
                row = json.loads(line)
                original = lookup[row["input"]]
                domain = original["extra_info"]["domain"]
                if domain in selected:
                    continue
                prompt = student.apply_chat_template(
                    original["prompt"], enable_thinking=False, add_generation_prompt=True, tokenize=False
                )
                prompt_ids = student.encode(prompt, add_special_tokens=False)
                response_ids = student.encode(row["output"], add_special_tokens=False)
                assert prompt_ids == teacher.encode(prompt, add_special_tokens=False)
                assert response_ids == teacher.encode(row["output"], add_special_tokens=False)
                selected[domain] = {
                    "domain": domain,
                    "sample_id": original["extra_info"]["sample_id"],
                    "source_step": step,
                    "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "prompt_length": len(prompt_ids),
                    "ids": prompt_ids + response_ids,
                    "cross_tokenizer_equal": True,
                    "scope": "re-encoded saved text; historical raw IDs, EOS and tensors were not saved",
                }
        samples = list(selected.values())
        assert len(samples) == 5
        eos = dict(samples[0])
        eos.update(domain="explicit_eos_control", ids=eos["ids"] + [student.eos_token_id])
        samples.append(eos)
        save(out / "samples.json", samples)
        print([(r["domain"], r["prompt_length"], len(r["ids"]) - r["prompt_length"]) for r in samples], flush=True)
        return
    samples = json.loads((out / "samples.json").read_text())
    if args.mode == "hf":
        import torch
        from transformers import AutoModelForImageTextToText

        result = {}
        for role, model_path, temperature in [("student", STUDENT, 0.8), ("teacher", TEACHER, 1.0)]:
            print("LOAD", role, flush=True)
            model = AutoModelForImageTextToText.from_pretrained(
                model_path, dtype=torch.bfloat16, device_map={"": 0}, attn_implementation="sdpa", local_files_only=True
            ).eval()
            scores = []
            for row in samples:
                ids = torch.tensor([row["ids"]], device="cuda")
                with torch.inference_mode():
                    logits = model(input_ids=ids, attention_mask=torch.ones_like(ids), use_cache=False).logits
                    values = []
                    for start in range(0, ids.shape[1] - 1, 64):
                        end = min(start + 64, ids.shape[1] - 1)
                        block = logits[0, start:end].float() / temperature
                        lp = block.gather(-1, ids[0, start + 1 : end + 1, None]).squeeze(-1) - block.logsumexp(-1)
                        values.extend(lp.cpu().tolist())
                    assert all(torch.isfinite(torch.tensor(values)))
                scores.append(values)
                del logits, ids, block, lp
                print(role, row["domain"], len(values), flush=True)
            result[role] = scores
            del model
            gc.collect()
            torch.cuda.empty_cache()
        save(out / "hf-replay.json", result)
        return
    if args.mode == "vllm":
        from vllm import LLM, SamplingParams

        from verl.workers.rollout.vllm_rollout.utils import extract_prompt_logprobs

        llm = LLM(
            model=TEACHER,
            dtype="bfloat16",
            tensor_parallel_size=1,
            gpu_memory_utilization=0.75,
            max_model_len=4096,
            max_num_seqs=1,
            max_num_batched_tokens=4096,
            enforce_eager=True,
            enable_prefix_caching=False,
        )
        outputs = llm.generate(
            [{"prompt_token_ids": r["ids"]} for r in samples],
            SamplingParams(max_tokens=1, temperature=1.0, prompt_logprobs=0),
        )
        result = []
        parser_checks = []
        for row, response in zip(samples, outputs, strict=True):
            assert row["ids"] == response.prompt_token_ids
            parsed = {}
            extract_prompt_logprobs(response, 0, parsed)
            assert [ids[0] for ids in parsed["prompt_ids"][:-1]] == row["ids"][1:]
            assert parsed["prompt_ids"][-1] == [0] and parsed["prompt_logprobs"][-1] == [0.0]
            parser_checks.append({"domain": row["domain"], "all_shifted_ids_equal": True, "dummy_tail_correct": True})
            result.append([response.prompt_logprobs[i][token].logprob for i, token in enumerate(row["ids"]) if i])
            assert [r[0] for r in parsed["prompt_logprobs"][:-1]] == result[-1]
        save(out / "vllm-replay.json", result)
        save(out / "native-parser-checks.json", parser_checks)
        return
    import numpy as np
    import torch
    from deep_numeric import SimpleNamespace, distillation_loss

    from verl.workers.config import DistillationLossConfig
    from verl.workers.utils.padding import no_padding_2_padding

    hf = json.loads((out / "hf-replay.json").read_text())
    served = json.loads((out / "vllm-replay.json").read_text())
    max_prompt = max(row["prompt_length"] for row in samples)
    max_response = max(len(row["ids"]) - row["prompt_length"] for row in samples)
    prompts, responses, attention, masks = [], [], [], []
    for row in samples:
        p = row["prompt_length"]
        r = len(row["ids"]) - p
        prompts.append([0] * (max_prompt - p) + row["ids"][:p])
        responses.append(row["ids"][p:] + [0] * (max_response - r))
        attention.append([0] * (max_prompt - p) + [1] * (p + r) + [0] * (max_response - r))
        masks.append([True] * r + [False] * (max_response - r))
    q = torch.tensor([v for row in hf["student"] for v in row + [0.0]], dtype=torch.float64, requires_grad=True)
    p = torch.tensor([v for row in served for v in row + [0.0]], dtype=torch.float64)
    mask = torch.tensor(masks)
    data = {
        "prompts": torch.tensor(prompts),
        "responses": torch.tensor(responses),
        "attention_mask": torch.tensor(attention),
        "response_mask": mask,
        "teacher_logprobs": p[:, None],
        "dp_size": 1,
        "batch_num_tokens": int(mask.sum()),
        "global_batch_size": len(samples),
    }
    data["old_log_probs"] = no_padding_2_padding(q.detach(), data)
    actor = SimpleNamespace(loss_agg_mode="token-mean", global_batch_info={}, loss_scale_factor=None)
    config = SimpleNamespace(
        distillation_loss=DistillationLossConfig(
            loss_mode="k1",
            use_policy_gradient=True,
            use_task_rewards=False,
        )
    )
    actual_loss, _ = distillation_loss(actor, config, {"log_probs": q}, data)
    actual_grad = torch.autograd.grad(actual_loss, q)[0]
    offsets, indices = 0, []
    for row in samples:
        indices.extend(range(offsets + row["prompt_length"] - 1, offsets + len(row["ids"]) - 1))
        offsets += len(row["ids"])
    delta = (q.detach()[indices] - p[indices]).clamp(-10, 10)
    expected_grad = torch.zeros_like(q)
    expected_grad[indices] = delta / len(indices)
    loss_error = abs(float(actual_loss.detach() - delta.mean()))
    gradient_error = float((actual_grad - expected_grad).abs().max())
    assert loss_error < 1e-8 and gradient_error < 1e-8
    save(
        out / "replay-loss-check.json",
        {
            "loss_error": loss_error,
            "gradient_error": gradient_error,
            "valid_response_tokens": len(indices),
            "scope": "real replay probabilities, controlled ratio=1; not historical optimizer state",
            "clipped_token_count": int(((q.detach()[indices] - p[indices]).abs() > 10).sum()),
            "passed": True,
        },
    )
    cases = []
    errors = []
    for i, row in enumerate(samples):
        start = row["prompt_length"] - 1
        reference = np.asarray(hf["teacher"][i])[start:]
        actual = np.asarray(served[i])[start:]
        assert len(actual) == len(row["ids"]) - row["prompt_length"]
        error = np.abs(reference - actual)
        errors.extend(error.tolist())
        cases.append(
            {
                "domain": row["domain"],
                "response_tokens": len(actual),
                "mean_abs_error": float(error.mean()),
                "p95_abs_error": float(np.quantile(error, 0.95)),
                "max_abs_error": float(error.max()),
                "wrong_shift_mean_abs_error": float(np.abs(reference[1:] - actual[:-1]).mean()),
                "first_error": float(error[0]),
                "last_error": float(error[-1]),
            }
        )
    save(
        out / "replay-verdict.json",
        {
            "scope": "five-domain TEXT replay plus explicit EOS control; not exact historical training tensors",
            "cases": cases,
            "response_tokens": len(errors),
            "mean_abs_error": float(np.mean(errors)),
            "p95_abs_error": float(np.quantile(errors, 0.95)),
            "passed": all(c["mean_abs_error"] < 0.1 and c["p95_abs_error"] < 0.5 for c in cases),
            "student_temperature": 0.8,
            "teacher_temperature": 1.0,
        },
    )
    print((out / "replay-verdict.json").read_text())


if __name__ == "__main__":
    main()
