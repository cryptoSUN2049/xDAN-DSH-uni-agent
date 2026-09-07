"""Parallel agent inference over a verl-launched engine, through the training path.

Same job as ``parallel_infer_api.py`` (run each row's task, report a score), but verl
brings the engine up and rollouts flow through the *exact* training stack -- the agent
framework adapter + TransferQueue (TQ):

    verl LLMServerManager (vLLM / SGLang)
    ->  AgentFrameworkRolloutAdapter.generate_sequences   (fire-and-forget -> TQ)
          ->  Gateway sessions (per-session OpenAI-compatible endpoints)
          ->  uni_agent.framework.task_runner.run_task  ->  uni_agent task
    ->  per-trajectory records written to TransferQueue

The per-sample score is the trainer's own ``rm_scores`` read back from TQ: ``run_task``
(``report_reward=True``) posts the task reward to its session, and the framework writes
it as ``reward_score`` -- no external reward model. Fan-out is ``rollout.n`` (``--n``),
with no resolved/wrong-answer/timeout bucketing (just mean ``rm_scores``).

Example (single node, 4-way tensor parallel)::

    python examples/inference/parallel_infer_verl.py \
        --data-path ~/data/swe_agent/swe_bench_verified.parquet \
        --model-path ~/models/Qwen3-Coder-30B-A3B-Instruct \
        --tool-parser qwen3_coder --tensor-parallel-size 4 \
        --task-config examples/quickstart/inference/task_config_react.yaml --limit 8

``--task-config`` is required (same YAML shape as ``parallel_infer_api.py``); the policy
endpoint is the gateway session, bound by the runner, not a flag.
"""

import argparse
import json
import logging
import math
import os
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
import ray
from omegaconf import OmegaConf

import verl

try:
    import transfer_queue as tq
except ImportError:  # fall back to verl's shim (mock raises a clear error if TQ is missing)
    from verl.utils.transferqueue_utils import tq

from uni_agent.tasks import TaskConfigResolver
from verl.utils import tensordict_utils as tu

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


GLOBAL_CONCURRENCY = int(os.getenv("GLOBAL_CONCURRENCY", 128))
PARTITION_ID = "val"

DEFAULT_TEMPERATURE = 0.8
DEFAULT_TOP_P = 0.9
DEFAULT_RESPONSE_LENGTH = 65536
DEFAULT_PROMPT_LENGTH = 4096


def _rule(text: str = "", width: int = 50, ch: str = "-") -> str:
    """A centered-title horizontal rule."""
    if not text:
        return ch * width
    pad = max(0, width - len(text) - 2)
    return f"{ch * (pad // 2)} {text} {ch * (pad - pad // 2)}"


def init_config(args: argparse.Namespace, *, task_configs: list[dict], served_model_name: str):
    """Compose verl's ``ppo_trainer`` config and override the engine + framework knobs."""
    from hydra import compose, initialize_config_dir

    config_dir = str(Path(verl.__file__).resolve().parent / "trainer" / "config")
    with initialize_config_dir(config_dir=config_dir, version_base=None):
        config = compose(config_name="ppo_trainer")

    rollout = config.actor_rollout_ref.rollout

    model_cfgs = [entry.get("agent", {}).get("model", {}) for entry in task_configs]
    temperature = model_cfgs[0].get("temperature", DEFAULT_TEMPERATURE)
    top_p = model_cfgs[0].get("top_p", DEFAULT_TOP_P)
    rollout.temperature = temperature
    rollout.top_p = top_p
    rollout.val_kwargs.temperature = temperature
    rollout.val_kwargs.top_p = top_p

    # response_length = the agent's episode token budget (max_total_tokens: the full
    # prompt+gen context the loop may consume); DEFAULT_RESPONSE_LENGTH is the fallback.
    max_total_tokens = max(
        (m.get("max_total_tokens", DEFAULT_RESPONSE_LENGTH) for m in model_cfgs),
        default=DEFAULT_RESPONSE_LENGTH,
    )
    response_length = int(max_total_tokens)

    # Fan-out: the framework runs rollout.n gateway sessions per prompt.
    rollout.n = max(1, args.n)
    rollout.val_kwargs.n = rollout.n

    # Hardware.
    rollout.nnodes = args.nnodes
    rollout.n_gpus_per_node = args.n_gpus_per_node
    config.trainer.nnodes = args.nnodes
    config.trainer.n_gpus_per_node = args.n_gpus_per_node

    # Model + engine.
    config.actor_rollout_ref.model.path = os.path.expanduser(args.model_path)
    rollout.name = args.engine
    rollout.mode = "async"
    # Standalone inference has no trainer to broadcast weights.
    rollout.load_format = "auto"
    rollout.prompt_length = DEFAULT_PROMPT_LENGTH
    rollout.response_length = response_length
    # Keep the engine context bounded by the framework batch contract.  The
    # VERL default (40960) reserves more KV cache than a single 24 GiB GPU can
    # provide alongside Qwen3-4B, even when the task asks for a short episode.
    max_model_len = args.max_model_len
    if max_model_len is None:
        max_model_len = DEFAULT_PROMPT_LENGTH + response_length
    if max_model_len < DEFAULT_PROMPT_LENGTH + response_length:
        raise ValueError("--max-model-len must cover the prompt and response lengths")
    rollout.max_model_len = max_model_len
    rollout.tensor_model_parallel_size = args.tensor_parallel_size
    rollout.gpu_memory_utilization = args.gpu_memory_utilization
    rollout.calculate_log_probs = True
    rollout.enable_rollout_routing_replay = args.enable_rollout_routing_replay
    rollout.disable_log_stats = False
    rollout.free_cache_engine = False
    OmegaConf.update(config, "actor_rollout_ref.rollout.enable_sleep_mode", False, force_add=True)

    # Gateway tool-call parser: the gateway decodes tool calls from raw tokens, so
    # this must match the model's chat template (the analog of vLLM's
    # --tool-call-parser, e.g. qwen3_coder for Qwen3-Coder, hermes for Qwen3).
    OmegaConf.update(config, "actor_rollout_ref.rollout.multi_turn.format", args.tool_parser, force_add=True)

    agent_framework_cfg = {
        "gateway_count": args.gateway_count,
        "agent_runners": {
            "task": {
                "runner_fqn": "uni_agent.framework.task_runner.run_task",
                "dispatch_mode": "ray_task",
                "max_concurrent_sessions": max(0, args.concurrency),
                "runner_kwargs": {
                    "task_config_path": args.task_config,
                    "model_name": served_model_name,
                    "report_reward": True,
                    "require_reward_post": args.require_reward_post,
                },
            }
        },
    }
    agent_framework_cfg["log_dir"] = args.log_dir
    runner_kwargs = agent_framework_cfg["agent_runners"]["task"]["runner_kwargs"]
    if args.dsh_trace_root is not None or args.dsh_result_root is not None:
        runner_kwargs.update(dsh_trace_root=args.dsh_trace_root, dsh_result_root=args.dsh_result_root)
    if args.dsh_strict_audit:
        runner_kwargs["require_reward_post"] = True
        agent_framework_cfg.update(
            use_reward_loop_worker=False,
            fail_on_rollout_error=True,
            require_finished_episode=True,
            require_verifier_reward=True,
            require_trajectory_dump=True,
            trajectory_postprocessor_fqn="uni_agent.tasks.dsh.trajectory_audit.validate_trajectories",
            trajectory_postprocessor_pass_context=True,
            trajectory_postprocessor_kwargs={"trace_root": args.dsh_trace_root, "result_root": args.dsh_result_root},
        )
    runner_kwargs.update(_episode_runner_kwargs(args))
    OmegaConf.update(config, "actor_rollout_ref.rollout.custom.agent_framework", agent_framework_cfg, force_add=True)

    # TransferQueue carries the rollout trajectories (and their rm_scores).
    OmegaConf.update(config, "transfer_queue.enable", True, force_add=True)

    # Data.
    config.data.return_raw_chat = True
    config.data.max_prompt_length = DEFAULT_PROMPT_LENGTH
    config.data.max_response_length = response_length
    # Match the bounded Qwen3 training launcher.  Otherwise the model's
    # default thinking block consumes the short episode budget and the
    # inference proof no longer exercises the same token/mask contract.
    OmegaConf.update(config, "data.apply_chat_template_kwargs.enable_thinking", False, force_add=True)

    return config


def _build_prompts(samples: list, uids: list):
    """Assemble the TensorDict batch the framework's ``generate_sequences`` expects."""
    return tu.get_tensordict(
        tensor_dict={
            "raw_prompt": [sample.get("prompt") for sample in samples],
            "uid": list(uids),
            "tools_kwargs": [sample["extra_info"]["tools_kwargs"] for sample in samples],
        },
        non_tensor_dict={"global_steps": None, "validate": True},
    )


def _read_rm_scores(uids: list, *, partition_id: str = PARTITION_ID) -> dict:
    """Read each session's final trajectory back from TQ and score it."""
    input_uids = set(uids)
    listing = tq.kv_list() or {}
    partition = listing.get(partition_id, {}) or {}

    # (uid, session) -> (max_index, key); also collect every key we touch for cleanup.
    final: dict[tuple[str, str], tuple[int, str]] = {}
    traj_keys: list[str] = []
    uid_status: dict[str, str] = {}
    for key, tag in partition.items():
        tag = tag or {}
        parts = key.rsplit("_", 2)
        if len(parts) != 3:
            # uid-level status marker (uid has no underscores: it is a uuid4 hex-with-dashes).
            if key in input_uids:
                uid_status[key] = tag.get("status")
            continue
        uid, session, index_str = parts
        if uid not in input_uids or tag.get("status") != "success":
            continue
        try:
            index = int(index_str)
        except ValueError:
            continue
        traj_keys.append(key)
        session_key = (uid, session)
        if session_key not in final or final[session_key][0] < index:
            final[session_key] = (index, key)

    # Deterministic order so scores align with the (uid, session) they came from.
    final_items = sorted(final.items())
    final_keys = [key for _, (_, key) in final_items]
    final_sessions = [session_key for session_key, _ in final_items]

    per_uid: dict[str, list[float]] = defaultdict(list)
    scores: list[float] = []
    if final_keys:
        data = tq.kv_batch_get(keys=final_keys, partition_id=partition_id, select_fields=["rm_scores"])
        scores = [float(s) for s in data["rm_scores"].sum(dim=-1).tolist()]
        for (uid, _session), score in zip(final_sessions, scores, strict=True):
            per_uid[uid].append(score)

    uid_keys = [uid for uid in input_uids if uid in uid_status]
    return {
        "scores": scores,
        "per_uid": dict(per_uid),
        "uid_status": uid_status,
        "final_keys": final_keys,
        "traj_keys": traj_keys,
        "uid_keys": uid_keys,
    }


def _report(
    read: dict, *, wall: float, num_prompts: int, n: int, args: argparse.Namespace, served_model_name: str
) -> None:
    """Print the mean-rm_scores summary and optionally persist a JSON result file."""
    scores = read["scores"]
    per_uid = read["per_uid"]
    uid_status = read["uid_status"]

    expected = num_prompts * n
    num_scored = len(scores)
    mean_score = float(np.mean(scores)) if scores else 0.0
    # Per-prompt score = mean over that prompt's sessions; then averaged over prompts.
    prompt_means = [float(np.mean(v)) for v in per_uid.values() if v]
    mean_over_prompts = float(np.mean(prompt_means)) if prompt_means else 0.0
    failed_uids = sum(1 for status in uid_status.values() if status != "finished")

    summary = "\n".join(
        [
            "",
            _rule("inference summary"),
            f"  mean rm_score      {mean_score:>8.4f}   (over {num_scored} sessions)",
            f"  mean over prompts  {mean_over_prompts:>8.4f}   (over {len(prompt_means)} prompts)",
            f"  scored sessions    {num_scored:>4} / {expected:<4} ({num_prompts} prompts x n={n})",
            f"  failed prompts     {failed_uids:>4}",
            _rule(f"wall {wall:.1f}s"),
            "",
        ]
    )
    print(summary)

    if args.result_path:
        result_path = os.path.expanduser(args.result_path)
        os.makedirs(os.path.dirname(result_path) or ".", exist_ok=True)
        payload = {
            "model_path": os.path.expanduser(args.model_path),
            "served_model_name": served_model_name,
            "data_path": os.path.expanduser(args.data_path),
            "task_config": args.task_config,
            "n": n,
            "num_prompts": num_prompts,
            "num_scored_sessions": num_scored,
            "mean_rm_score": mean_score,
            "mean_rm_score_over_prompts": mean_over_prompts,
            "scores": scores,
            "scores_by_uid": per_uid,
        }
        with open(result_path, "w") as f:
            json.dump(payload, f, indent=2)
        logger.info(f"wrote result file to: {result_path}")


def _load_samples(args: argparse.Namespace) -> list:
    from datasets import load_dataset

    samples = load_dataset("parquet", data_files=args.data_path, split="train").to_list()
    return samples[: args.limit] if args.limit is not None else samples


def _generate(config, samples: list, uids: list) -> float:
    """Initialize the real engine and run the pre-registered inputs through TQ."""
    from uni_agent.framework.entry import AgentFrameworkRolloutAdapter
    from verl.workers.rollout.llm_server import LLMServerManager

    ray.init()
    tq.init(config.transfer_queue)
    llm_server_manager = LLMServerManager.create(config=config)
    adapter = AgentFrameworkRolloutAdapter.create(
        config=config,
        llm_client=llm_server_manager.get_client(),
    )
    prompts = _build_prompts(samples, uids)
    logger.info("starting inference...")
    begin_time = time.time()
    adapter.generate_sequences_and_wait(prompts)
    return time.time() - begin_time


def _validate_evidence_args(args: argparse.Namespace) -> None:
    if args.dsh_strict_audit:
        for field in ("dsh_trace_root", "dsh_result_root", "inference_evidence_path", "log_dir", "result_path"):
            value = getattr(args, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"--dsh-strict-audit requires --{field.replace('_', '-')}")
        if args.n != 1:
            raise ValueError("--dsh-strict-audit requires --n=1")
    roots = (args.dsh_trace_root, args.dsh_result_root)
    if any(value is not None for value in roots):
        for field, value in zip(("dsh_trace_root", "dsh_result_root"), roots, strict=True):
            if not value or not Path(value).is_absolute() or ".." in Path(value).parts:
                raise ValueError(f"--{field.replace('_', '-')} must be an absolute traversal-free path")
    if args.inference_evidence_path:
        path = Path(args.inference_evidence_path).expanduser()
        if os.path.lexists(path):
            raise FileExistsError("--inference-evidence-path already exists")
        if args.result_path and path.resolve() == Path(args.result_path).expanduser().resolve():
            raise ValueError("--inference-evidence-path must differ from --result-path")
    _validate_episode_args(args)


def _validate_episode_args(args: argparse.Namespace) -> None:
    episode_fields = ("dsh_episode_workdir_root", "dsh_episode_source_root", "dsh_episode_files")
    if any(getattr(args, field) is not None for field in episode_fields):
        if not args.dsh_strict_audit:
            raise ValueError("DSH episode workdirs require --dsh-strict-audit")
        if not all(getattr(args, field) for field in episode_fields):
            raise ValueError("DSH episode workdir root, source root and files must be configured together")
        for field in episode_fields:
            path = Path(getattr(args, field))
            if not path.is_absolute() or ".." in path.parts:
                raise ValueError(f"--{field.replace('_', '-')} must be an absolute traversal-free path")


def _episode_runner_kwargs(args: argparse.Namespace) -> dict:
    _validate_episode_args(args)
    if args.dsh_episode_files is None:
        return {}
    from uni_agent.framework.task_runner import _dsh_episode_path, _read_dsh_episode_files, _validate_dsh_episode_files

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate DSH episode file field")
            result[key] = value
        return result

    files_path = _dsh_episode_path(args.dsh_episode_files)
    files = _validate_dsh_episode_files(
        json.loads(files_path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    )
    _dsh_episode_path(args.dsh_episode_workdir_root)
    # Verify source bytes before the inference engine starts, and again in each runner.
    _read_dsh_episode_files(args.dsh_episode_source_root, files)
    return {
        "dsh_episode_workdir_root": args.dsh_episode_workdir_root,
        "dsh_episode_source_root": args.dsh_episode_source_root,
        "dsh_episode_files": files,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _write_evidence(path: Path, payload: dict, *, create: bool = False) -> None:
    """Publish complete JSON atomically; initial creation never replaces an existing run."""
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
            if create:
                os.link(temporary, path)
            else:
                os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def _registered_samples(samples: list, uids: list, resolver: TaskConfigResolver, *, strict: bool) -> list:
    rows = []
    for index, (sample, uid) in enumerate(zip(samples, uids, strict=True)):
        task = sample["extra_info"]["tools_kwargs"]["task"]
        if strict and task.get("name") != "dsh_architecture":
            raise ValueError("--dsh-strict-audit requires dsh_architecture tasks")
        metadata = resolver.resolve(task).get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("Task metadata must be an object")
        # Freeze the input identity without copying model configuration or credentials.
        rows.append({"uid": uid, "sample_index": index, "metadata": json.loads(json.dumps(metadata, allow_nan=False))})
    return rows


def _require_complete_readback(read: dict, uids: list, n: int) -> None:
    sessions = [key.rsplit("_", 2)[:2] for key in read["final_keys"]]
    expected = sorted((uid, str(index)) for uid in uids for index in range(n))
    if (
        sorted(map(tuple, sessions)) != expected
        or len(read["scores"]) != len(expected)
        or any(not math.isfinite(score) for score in read["scores"])
        or any(read["uid_status"].get(uid) != "finished" for uid in uids)
    ):
        raise RuntimeError("strict inference readback is incomplete or invalid")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parallel agent inference over a verl-launched engine (framework + TQ)."
    )

    # Input / output.
    parser.add_argument(
        "--data-path",
        default=os.getenv("DATA_PATH", os.path.expanduser("~/data/swe_agent/swe_bench_verified.parquet")),
        help="Path to the input dataset (Parquet format).",
    )
    parser.add_argument(
        "--model-path",
        "--model",
        dest="model_path",
        default=os.path.expanduser("~/models/Qwen3-Coder-30B-A3B-Instruct"),
        help="Local model checkpoint the engine loads.",
    )
    parser.add_argument(
        "--served-model-name",
        default=None,
        help="Model name sent on chat-completions requests (default: basename of --model-path).",
    )
    parser.add_argument(
        "--task-config",
        required=True,
        help="Path to a YAML task config: one ``- name: ...`` entry or a list of them (required). "
        "run_task routes each row to the entry whose 'name' matches the row's task; all agent/model "
        "knobs (sampling, max_total_tokens, max_steps, ...) come from it. The endpoint is bound to the "
        "gateway session.",
    )
    parser.add_argument(
        "--result-path",
        default=None,
        help="Optional path to write a JSON result file (mean rm_score and per-session scores).",
    )
    parser.add_argument(
        "--limit",
        "--max-samples",
        dest="limit",
        type=int,
        default=None,
        help="Only run the first N samples (smoke testing); omit for the full dataset.",
    )

    parser.add_argument(
        "--n", type=int, default=1, help="Rollout sessions per instance (rollout.n; scores average over all)."
    )

    # Engine / hardware.
    parser.add_argument(
        "--engine",
        default="vllm",
        choices=["vllm", "sglang"],
        help="Inference engine backend.",
    )
    parser.add_argument(
        "--enable-rollout-routing-replay",
        action="store_true",
        help="Enable R3 routed-expert capture in the rollout engine for routing-replay diagnostics.",
    )
    parser.add_argument("--nnodes", type=int, default=1, help="Number of nodes to run the engine on.")
    parser.add_argument("--n-gpus-per-node", type=int, default=8, help="Number of GPUs per node.")
    parser.add_argument(
        "--tensor-parallel-size", "--tp", dest="tensor_parallel_size", type=int, default=4, help="Tensor parallel size."
    )
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.9, help="Engine GPU memory fraction.")
    parser.add_argument(
        "--max-model-len",
        type=int,
        default=(int(os.environ["MAX_MODEL_LEN"]) if os.getenv("MAX_MODEL_LEN") else None),
        help="Maximum engine context length (default: prompt length + task response budget).",
    )
    parser.add_argument(
        "--gateway-count",
        type=int,
        default=4,
        help="Number of gateway actors fronting the engine (each serves many concurrent sessions).",
    )
    parser.add_argument(
        "--tool-parser",
        default=os.getenv("TOOL_PARSER", "qwen3_coder"),
        help="Gateway tool-call parser; MUST match the model's chat template (e.g. qwen3_coder, hermes).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=GLOBAL_CONCURRENCY,
        help="Max in-flight gateway sessions for the runner (runner.max_concurrent_sessions; env GLOBAL_CONCURRENCY).",
    )
    parser.add_argument(
        "--require-reward-post",
        action="store_true",
        help="Fail a rollout when the session reward endpoint is absent or does not acknowledge the reward POST.",
    )
    parser.add_argument(
        "--log-dir",
        default=os.getenv("UNI_AGENT_LOG_DIR", "/tmp/uni_agent_logs"),
        help="Root directory for per-session logs and trajectories; use an empty value to disable.",
    )
    parser.add_argument(
        "--dsh-strict-audit", action="store_true", help="Require DSH admission and persistent evidence."
    )
    parser.add_argument(
        "--dsh-trace-root", help="Absolute root for DSH trace artifacts; configure with --dsh-result-root."
    )
    parser.add_argument("--dsh-result-root", help="Absolute root for DSH Task envelopes and verifier receipts.")
    parser.add_argument(
        "--inference-evidence-path", help="New JSON file for input identity and actual TQ readback evidence."
    )
    parser.add_argument("--dsh-episode-workdir-root", help="Strict-only root for new Gateway-session task directories.")
    parser.add_argument("--dsh-episode-source-root", help="Strict-only root containing the frozen episode input files.")
    parser.add_argument(
        "--dsh-episode-files", help="Strict-only absolute path to the operator's JSON file/digest list."
    )
    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args()
    _validate_evidence_args(args)
    evidence_path = Path(args.inference_evidence_path).expanduser() if args.inference_evidence_path else None
    evidence = {
        "schema": "dsh.inference-evidence.v1",
        "status": "running",
        "started_at": _utc_now(),
        "finished_at": None,
        "partition_id": PARTITION_ID,
        "global_steps": None,
        "samples": [],
        "readback": None,
    }
    if evidence_path is not None:
        _write_evidence(evidence_path, evidence, create=True)
    try:
        resolver = TaskConfigResolver.from_file(args.task_config)
        served_model_name = args.served_model_name or os.path.basename(os.path.expanduser(args.model_path).rstrip("/"))
        samples = _load_samples(args)
        if not samples:
            if args.dsh_strict_audit:
                raise ValueError("strict inference requires at least one sample")
            logger.warning("no samples selected; exiting")
            evidence["status"] = "completed"
            return
        n = max(1, args.n)
        uids = [str(uuid4()) for _ in samples]
        if evidence_path is not None:
            evidence["samples"] = _registered_samples(samples, uids, resolver, strict=args.dsh_strict_audit)
            _write_evidence(evidence_path, evidence)
        logger.info(f"loaded {len(samples)} prompts (x n={n} sessions each) from {args.data_path}")
        config = init_config(
            args, task_configs=list(resolver.defaults_by_name.values()), served_model_name=served_model_name
        )
        wall = _generate(config, samples, uids)
        read = _read_rm_scores(uids, partition_id=PARTITION_ID)
        if evidence_path is not None and read["final_keys"]:
            readback = {key: read[key] for key in ("final_keys", "scores", "uid_status", "traj_keys")}
            # Reject non-JSON scores before claiming that a usable readback exists.
            json.dumps(readback, allow_nan=False)
            evidence["readback"] = readback
        if args.dsh_strict_audit:
            _require_complete_readback(read, uids, n)
        _report(read, wall=wall, num_prompts=len(samples), n=n, args=args, served_model_name=served_model_name)
        evidence["status"] = "completed"
    except BaseException as exc:
        evidence.update(status="failed", error_type=type(exc).__name__)
        raise
    finally:
        if evidence_path is not None:
            evidence["finished_at"] = _utc_now()
            _write_evidence(evidence_path, evidence)


if __name__ == "__main__":
    main()
