"""Hash-bound public T2 task rows for the existing dsh_architecture task."""

import json
from pathlib import Path

from examples.dsh.capability_tasks.log_tool.oracle import EMAIL_PATTERN
from examples.dsh.evolution_v3_live import _bundle_identity
from examples.dsh.verifier import _require_digest, _sha256_bytes
from uni_agent.agents.dsh.runner import _patches_digest

DIRECTORY = Path("examples/dsh/capability_tasks/log_tool")
VERIFIER_ID = "dsh-log-tool-verifier"
CODE_PATHS = (
    DIRECTORY / "oracle.py",
    DIRECTORY / "verifier.py",
    DIRECTORY / "verifier_cli.py",
    DIRECTORY / "task_bundle.py",
    Path("examples/dsh/evolution_verifier.py"),
    Path("examples/dsh/verifier.py"),
    Path("examples/dsh/evolution_v3_live.py"),
    Path("examples/dsh/evolution_v3_catalog.py"),
    Path("examples/dsh/evolution_v3_verifier.py"),
    Path("uni_agent/agents/dsh/runner.py"),
)


def load_case(path):
    raw = Path(path).read_bytes()
    case = json.loads(raw)
    if (
        case.get("schema") != "dsh.t2-log-tool-case.v1"
        or case.get("public") is not True
        or case.get("split") not in {"train", "dev"}
        or not isinstance(case.get("case_id"), str)
        or not case["case_id"]
        or not isinstance(case.get("calls"), list)
        or len(case["calls"]) < 2
    ):
        raise ValueError("Invalid public T2 case")
    for call in case["calls"]:
        if not isinstance(call, dict) or set(call) != {"records", "severity", "service"}:
            raise ValueError("T2 call requires records/severity/service")
        if not isinstance(call["records"], list) or any(
            call[key] is not None and not isinstance(call[key], str) for key in ("severity", "service")
        ):
            raise ValueError("Invalid T2 call arguments")
    if len({json.dumps(call["records"], sort_keys=True) for call in case["calls"]}) < 2:
        raise ValueError("T2 requires distinct record inputs")
    return case, raw


def build_rows(root, *, environment_digest, patches):
    root = Path(root).resolve()
    _require_digest(environment_digest, label="environment_digest")
    bundle = _bundle_identity(CODE_PATHS, repository_root=root)
    rows = []
    seen = set()
    for path in sorted((root / DIRECTORY / "fixtures").glob("*.json")):
        case, raw = load_case(path)
        if case["case_id"] in seen:
            raise ValueError("Duplicate T2 case identity")
        seen.add(case["case_id"])
        relative = path.relative_to(root).as_posix()
        split = "train" if case["split"] == "train" else "validation"
        prompt = (
            "Implement a reusable DSH runtime tool named filter_redact_logs and complete this log-processing task. "
            "Public task inputs (execute each calls entry): " + json.dumps(case["calls"], separators=(",", ":")) + ". "
            "The tool takes records (JSON array), severity and service (string or null). "
            "Skip records unless timestamp/service/severity/message are all strings; project those four fields. "
            "Apply case-sensitive exact severity and service filters with AND; null means no filter. "
            "Preserve order and duplicates. Replace ASCII email addresses in message with [REDACTED_EMAIL]. "
            "The exact public email matching pattern is " + EMAIL_PATTERN.pattern + ". Apply to all matches. "
            "First inspect the empty Plugin inventory, then use live Tool inventory to establish the tool is absent. "
            "Define and run one session-local "
            "host Plugin implementing this tool. Inspect that same Plugin until running "
            "and verify its tool is visible. "
            "Actually call the registered tool for every fixture calls entry. Then stop that Plugin, verify its tool "
            "is no longer visible, undefine the Plugin and inspect the empty Plugin inventory. "
            "Do not use shell/process tools or edit files. Do not claim a reward. One tool call per turn. "
            "Finish with a concise factual report. This is public development data, not hidden evaluation."
        )
        metadata = dict(
            task_id=case["case_id"],
            task_version="1",
            split=split,
            fixture_path=relative,
            fixture_digest=_sha256_bytes(raw),
            environment_digest=environment_digest,
            verifier_id=VERIFIER_ID,
            verifier_version="1",
            verifier_code_digest=bundle["sha256"],
            profile="sdk-minimal",
            patches_sha256=_patches_digest(tuple(patches)),
            patch_files={str(Path(p).resolve()): _sha256_bytes(Path(p).read_bytes()) for p in patches},
            evaluation_visibility="public",
        )
        rows.append(
            dict(
                uid=case["case_id"],
                data_source="dsh/t2-log-tool/" + split,
                agent_name="task",
                prompt=[dict(role="user", content=prompt)],
                extra_info={"tools_kwargs": {"task": {"name": "dsh_architecture", "metadata": metadata}}},
            )
        )
    if not rows:
        raise ValueError("No public T2 fixtures")
    return rows, bundle
