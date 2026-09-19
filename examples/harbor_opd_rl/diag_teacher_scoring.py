"""Check the OPD teacher scores the way training computed them, on real trajectories.

    python examples/harbor_opd_rl/diag_teacher_scoring.py vllm   --step-dir D --out O/vllm-prod.npz
    python examples/harbor_opd_rl/diag_teacher_scoring.py vllm   --step-dir D --out O/vllm-plain.npz --plain
    python examples/harbor_opd_rl/diag_teacher_scoring.py hf     --step-dir D --out O/hf.npz --groups g1,g2
    python examples/harbor_opd_rl/diag_teacher_scoring.py report --step-dir D --dir O

D is a train step's agent-log dir (runs/<run>/train/agent-logs/<project>/<exp>/step_N). Every
session there holds trajectory.npz with the exact token ids the teacher scored
(prompt_ids + response_ids), the loss mask and the student's sampling logprobs.

vllm: scores them with the production teacher engine settings (S1 train log, vLLM 0.23:
bf16, max_model_len 36865, max_num_seqs 4, chunked prefill with 4096 batched tokens,
prefix caching, processed_logprobs, eager) and VERL's own extract_prompt_logprobs with the
production sampling params (teacher_manager._get_teacher_sampling_params for k1). Qwen3.8
is a hybrid (linear-attention) model, so prefix caching and chunked prefill both touch the
recurrent state; --plain turns prefix caching off (chunking stays; hf is unchunked). The first group is scored a second
time at the end, when its prefix is fully cached.
hf: an independent reference with transformers (full forward, log_softmax, gather).
report: row i must be log p(token i+1 | tokens <= i) (checked through the returned ids and
against hf, also shifted by one); the loss reads rows from prompt_length-1 on mask-1 tokens.
It then rebuilds the step's distillation loss (k1 = student - teacher, clamped as in
training) to compare with the logged actor/distillation/loss, and relates the per-trajectory
teacher signal to the verifier reward.
"""

from __future__ import annotations

import argparse
import glob
import json
import os

import numpy as np

TEACHER = "/tmp/models/Qwen3.8-27B"


def load_sessions(step_dir: str, groups: set[str] | None = None) -> list[dict]:
    out = []
    for s in sorted(glob.glob(os.path.join(step_dir, "session-*"))):
        try:
            meta = json.load(open(os.path.join(s, "trajectory.json")))
            z = np.load(os.path.join(s, "trajectory.npz"))
        except (OSError, ValueError):
            continue  # a session killed before its dump
        if meta.get("num_trajectories") != 1:
            continue
        group = meta["group_uid"][:8]
        if groups and group not in groups:
            continue
        reward = None
        try:
            reward = float(open(os.path.join(s, "harbor", "verifier", "reward.txt")).read().strip())
        except (OSError, ValueError):
            pass
        out.append(
            {
                "key": os.path.basename(s),
                "group": group,
                "reward": reward,
                "prompt": z["traj0_prompt_ids"].astype(np.int64),
                "response": z["traj0_response_ids"].astype(np.int64),
                "mask": z["traj0_response_mask"].astype(bool),
                "student_lp": z["traj0_response_logprobs"].astype(np.float64),
            }
        )
    out.sort(key=lambda r: (r["group"], r["key"]))
    return out


def cmd_vllm(args) -> None:
    from vllm import LLM, SamplingParams
    from vllm.inputs import TokensPrompt

    from verl.workers.rollout.vllm_rollout.utils import extract_prompt_logprobs

    sessions = load_sessions(args.step_dir)
    engine = dict(
        model=TEACHER,
        dtype="bfloat16",
        max_model_len=36865,
        max_num_seqs=4,
        enable_chunked_prefill=True,
        max_num_batched_tokens=4096,
        enable_prefix_caching=True,
        logprobs_mode="processed_logprobs",
        enforce_eager=True,
        gpu_memory_utilization=0.7,
        seed=42,
        tensor_parallel_size=1,
    )
    if args.plain:
        # Prefix caching off, chunking kept: an unchunked 21k-token prefill needs ~20 GB for the
        # prompt-logprob log_softmax and OOMs at 0.7; the hf reference is the unchunked path.
        engine.update(enable_prefix_caching=False)
    llm = LLM(**engine)
    params = SamplingParams(max_tokens=1, temperature=1.0, prompt_logprobs=0, detokenize=False)
    first_group = [r for r in sessions if r["group"] == sessions[0]["group"]]
    order = sessions + ([] if args.plain else first_group)
    prompts = [TokensPrompt(prompt_token_ids=np.concatenate([r["prompt"], r["response"]]).tolist()) for r in order]
    outputs = llm.generate(prompts, params)
    saved = {}
    for i, (r, o) in enumerate(zip(order, outputs, strict=True)):
        res: dict[str, list] = {}
        extract_prompt_logprobs(o, 0, res)
        tag = r["key"] + ("#cached" if i >= len(sessions) else "")
        saved[tag + "/lp"] = np.array([x[0] for x in res["prompt_logprobs"]], dtype=np.float64)
        saved[tag + "/ids"] = np.array([x[0] for x in res["prompt_ids"]], dtype=np.int64)
    np.savez(args.out, **saved, engine=json.dumps(engine))
    print("saved", args.out, len(order), "sequences")


def cmd_hf(args) -> None:
    import torch
    import transformers

    groups = set(args.groups.split(",")) if args.groups else None
    sessions = load_sessions(args.step_dir, groups)
    config = transformers.AutoConfig.from_pretrained(TEACHER)
    cls = getattr(transformers, config.architectures[0])
    model = cls.from_pretrained(TEACHER, dtype=torch.bfloat16, device_map="cuda:0").eval()
    saved = {}
    with torch.no_grad():
        for r in sessions:
            ids = torch.tensor(np.concatenate([r["prompt"], r["response"]]), device="cuda:0")[None]
            hidden = model.model(input_ids=ids, use_cache=False).last_hidden_state[0]
            rows = torch.zeros(ids.shape[1], dtype=torch.float64)
            for a in range(0, ids.shape[1] - 1, 2048):
                b = min(a + 2048, ids.shape[1] - 1)
                logp = torch.log_softmax(model.lm_head(hidden[a:b]).float(), dim=-1)
                rows[a:b] = logp.gather(-1, ids[0, a + 1 : b + 1, None])[:, 0].double().cpu()
            saved[r["key"] + "/lp"] = rows.numpy()  # row i = log p(token i+1 | <= i); last row 0
            print(r["key"], ids.shape[1], flush=True)
    np.savez(args.out, **saved)


def response_rows(rows: np.ndarray, r: dict) -> np.ndarray:
    """The loss's view: rows prompt_length-1 .. prompt_length-1+response_length-1."""
    p = len(r["prompt"])
    return rows[p - 1 : p - 1 + len(r["response"])]


def verl_function_check(sessions: list[dict], prod) -> dict:
    import torch
    from tensordict import TensorDict

    from verl.trainer.ppo.core_algos import kl_penalty_forward
    from verl.workers.utils.padding import no_padding_2_padding

    def nested(xs):
        return torch.nested.as_nested_tensor([torch.as_tensor(x) for x in xs], layout=torch.jagged)

    teacher_full, student_full = [], []
    for r in sessions:
        p, n = len(r["prompt"]), len(r["prompt"]) + len(r["response"])
        teacher_full.append(torch.tensor(prod[r["key"] + "/lp"], dtype=torch.float64)[:, None])
        s = torch.zeros(n, dtype=torch.float64)
        s[p - 1 : n - 1] = torch.tensor(r["student_lp"])
        student_full.append(s)
    data = TensorDict(
        {"prompts": nested([r["prompt"] for r in sessions]), "responses": nested([r["response"] for r in sessions])},
        batch_size=[len(sessions)],
    )
    teacher = no_padding_2_padding(nested(teacher_full), data).squeeze(-1)
    student = no_padding_2_padding(nested(student_full), data)
    k1 = kl_penalty_forward(student, teacher, "k1").clamp(min=-10.0, max=10.0)
    worst_slice, worst_student, worst_k1 = 0.0, 0.0, 0.0
    for b, r in enumerate(sessions):
        m, n = r["mask"], len(r["response"])
        manual_t = response_rows(prod[r["key"] + "/lp"], r)
        worst_slice = max(worst_slice, float(np.abs(teacher[b, :n].numpy() - manual_t)[m].max()))
        worst_student = max(worst_student, float(np.abs(student[b, :n].numpy() - r["student_lp"])[m].max()))
        manual_k1 = np.clip(r["student_lp"] - manual_t, -10.0, 10.0)
        worst_k1 = max(worst_k1, float(np.abs(k1[b, :n].numpy() - manual_k1)[m].max()))
    return {
        "teacher_slice_max_abs_diff": worst_slice,
        "student_slice_max_abs_diff": worst_student,
        "k1_max_abs_diff": worst_k1,
    }


def cmd_report(args) -> None:
    sessions = load_sessions(args.step_dir)
    runs = {name: np.load(os.path.join(args.dir, f"{name}.npz")) for name in ("vllm-prod", "vllm-plain", "hf")}
    report: dict = {"sequences": len(sessions)}

    # 1. Alignment through the ids vLLM returned: row i must carry token i+1.
    prod = runs["vllm-prod"]
    bad = 0
    for r in sessions:
        seq = np.concatenate([r["prompt"], r["response"]])
        ids = prod[r["key"] + "/ids"]
        bad += int((ids[:-1] != seq[1:]).sum())
    report["id_misaligned_rows"] = bad

    # 2. Values against the independent reference and against each other, on loss tokens only.
    def diff(a_name, b_name, a_suffix="", shift=0):
        d = []
        for r in sessions:
            ka, kb = r["key"] + a_suffix + "/lp", r["key"] + "/lp"
            if ka not in runs[a_name] or kb not in runs[b_name]:
                continue
            a = response_rows(runs[a_name][ka], r)
            b = response_rows(np.roll(runs[b_name][kb], -shift), r)
            d.append(np.abs(a - b)[r["mask"]])
        if not d:
            return None
        d = np.concatenate(d)
        q99 = float(np.quantile(d, 0.99))
        return {"tokens": int(d.size), "mean": float(d.mean()), "p99": q99, "max": float(d.max())}

    report["prod_vs_hf"] = diff("vllm-prod", "hf")
    report["plain_vs_hf"] = diff("vllm-plain", "hf")
    report["prod_vs_plain"] = diff("vllm-prod", "vllm-plain")
    report["prod_cached_vs_prod"] = diff("vllm-prod", "vllm-prod", a_suffix="#cached")
    report["prod_vs_hf_shifted_by_1"] = diff("vllm-prod", "hf", shift=1)

    # 3. The production functions on real shapes: VERL's no_padding_2_padding (the loss's
    #    slice of packed full-sequence rows) and kl_penalty_forward("k1"), against the manual
    #    slice above. The student rows are placed the way the actor produces them (row i =
    #    log p(token i+1), labels from torch.roll(input_ids, -1)).
    report["verl_functions"] = verl_function_check(sessions, prod)

    # 4. Rebuild the step's distillation loss as training computed it: k1 = student - teacher
    #    (kl_penalty_forward), then clamp to +-loss_max_clamp=10 (distillation/losses.py:258);
    #    log_prob_min_clamp only applies to the top-k losses. Training used the actor's
    #    recomputed student logprobs; the sampling logprobs here differ by the logged
    #    rollout_corr/kl (~5e-4).
    k1_all, k1_raw, per_traj = [], [], []
    for r in sessions:
        raw = (r["student_lp"] - response_rows(prod[r["key"] + "/lp"], r))[r["mask"]]
        k1 = np.clip(raw, -10.0, 10.0)
        k1_all.append(k1)
        k1_raw.append(raw)
        per_traj.append(
            {
                "key": r["key"][15:40],
                "group": r["group"],
                "reward": r["reward"],
                "loss_tokens": int(r["mask"].sum()),
                "k1_mean": round(float(k1.mean()), 4),
                "opd_adv_sum": round(float(-k1.sum()), 1),
                "share_k1_gt_2": round(float((k1 > 2).mean()), 4),
                "share_k1_lt_-2": round(float((k1 < -2).mean()), 4),
            }
        )
    k1_all = np.concatenate(k1_all)
    report["k1_token_mean"] = float(k1_all.mean())
    report["k1_token_mean_unclamped"] = float(np.concatenate(k1_raw).mean())
    report["k1_abs_mean_unclamped"] = float(np.abs(np.concatenate(k1_raw)).mean())
    report["k1_quantiles"] = {q: float(np.quantile(k1_all, q)) for q in (0.01, 0.1, 0.5, 0.9, 0.99)}
    rewarded = [p for p in per_traj if p["reward"] is not None]
    if len({p["reward"] for p in rewarded}) > 1:
        y = np.array([p["reward"] for p in rewarded])
        for f in ("k1_mean", "opd_adv_sum", "loss_tokens"):
            x = np.array([p[f] for p in rewarded], dtype=float)
            report[f"corr_reward_{f}"] = float(np.corrcoef(x, y)[0, 1])
    report["per_trajectory"] = per_traj
    text = json.dumps(report, indent=1)
    open(os.path.join(args.dir, "report.json"), "w").write(text)
    print(text)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("vllm")
    v.add_argument("--step-dir", required=True)
    v.add_argument("--out", required=True)
    v.add_argument("--plain", action="store_true")
    h = sub.add_parser("hf")
    h.add_argument("--step-dir", required=True)
    h.add_argument("--out", required=True)
    h.add_argument("--groups", default="")
    r = sub.add_parser("report")
    r.add_argument("--step-dir", required=True)
    r.add_argument("--dir", required=True)
    args = ap.parse_args()
    {"vllm": cmd_vllm, "hf": cmd_hf, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
