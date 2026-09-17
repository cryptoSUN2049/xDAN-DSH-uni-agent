#!/usr/bin/env bash
# Stage data: download Terminal-Bench 2.1 from Harbor Hub into parquet with the
# upstream preprocessor, and build the training subset (TASK_FILTER=easy uses the
# four tasks labelled easy; all uses the first MAX_INSTANCES). No GPU.
STAGE_NAME=data
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"; stage_dir

# DATASET=stage1: private HF repo gump2049/xDAN-Harbor-Stage1-Tasks (Harbor task
# dirs under <source>/<rev>/runtime-v1/<task>, index/tasks.jsonl with split +
# difficulty). STAGE1_SLICE=N takes the first N train tasks in index order
# (20 -> 100 -> all as the dataset grows); STAGE1_SOURCES filters sources.
# STAGE1_TRAIN_PER_SOURCE / STAGE1_VAL_PER_SOURCE select per-source quotas instead
# (e.g. STAGE1_REPO=gump2049/xDAN-Harbor-Stage1-Tasks-Full with 50 / 20). Tasks in a
# shared eval-set-*/reserved.json are always excluded unless STAGE1_EXCLUDE_RESERVED=0.
# Validation split becomes the held-out parquet. Only audit-passed tasks are kept unless
# STAGE1_REQUIRE_AUDIT=0. Needs HF_TOKEN or ~/.cache/huggingface/token.
DATASET="${DATASET:-tb21}"
if [[ "${DATASET}" == stage1 ]]; then
  STAGE1_REPO="${STAGE1_REPO:-gump2049/xDAN-Harbor-Stage1-Tasks}"
  STAGE1_SLICE="${STAGE1_SLICE:-20}"          # 0 = all
  STAGE1_SOURCES="${STAGE1_SOURCES:-terminal-lego-15k swe-rebench-v2-fv}"
  S1="${DATA_DIR}/stage1"; mkdir -p "${S1}"
  "${LANE_PY}" - "${STAGE1_REPO}" "${S1}/repo" "${STAGE1_SLICE}" "${STAGE1_SOURCES}" "${S1}" > "${STAGE_DIR}/stage1-select.log" 2>&1 <<'PY'
import glob, itertools, json, os, shutil, sys, tarfile
from huggingface_hub import snapshot_download
repo, local, slice_n, sources, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4].split(), sys.argv[5]
# The audited repo ships unpacked task dirs; the Full repo ships one
# <batch>/<rev>/runtime-v1.tar.gz per source plus per-task audit sidecars.
path = snapshot_download(repo, repo_type="dataset", local_dir=local, allow_patterns=[
    "index/*", "*/runtime-v1/*", "*/runtime-v1.tar.gz", "audits/*/audit-status.jsonl", "eval-set-*/reserved.json"])
rows = [json.loads(l) for l in open(os.path.join(path, "index", "tasks.jsonl"))]
rows = [r for r in rows if r["source"] in sources and r["status"] == "derived"]
# Audit sidecars (Full repo): audits/*/audit-status.jsonl rows {task, status}. They
# fill nop_oracle_audit where the index leaves it null.
sidecar = {}
for audit_file in sorted(glob.glob(os.path.join(path, "audits", "*", "audit-status.jsonl"))):
    for line in open(audit_file):
        entry = json.loads(line)
        sidecar[entry["task"]] = {"passed": entry.get("status") == "passed", "sidecar": os.path.relpath(audit_file, path)}
merged = 0
for r in rows:
    if r.get("nop_oracle_audit") is None and r["task"] in sidecar:
        r["nop_oracle_audit"] = sidecar[r["task"]]; merged += 1
print("audit sidecar entries", len(sidecar), "merged", merged)
# Only tasks whose no-op/oracle sandbox audit passed (nop reward 0, oracle 1) are
# trainable by default: a task that pays the no-op agent teaches reward hacking,
# one the oracle cannot solve only burns sandboxes. Unaudited tasks need an
# explicit STAGE1_REQUIRE_AUDIT=0.
require_audit = os.environ.get("STAGE1_REQUIRE_AUDIT", "1") == "1"
before_audit = len(rows)
if require_audit:
    rows = [r for r in rows if isinstance(r.get("nop_oracle_audit"), dict) and r["nop_oracle_audit"].get("passed") is True]
print("audit filter", "on" if require_audit else "off", before_audit, "->", len(rows))
# Shared evaluation sets (eval-set-*/reserved.json, frozen jointly with the Tinker line)
# are never trained on: Terminal-Lego by task id, swe-rebench by repository (task id
# with its trailing "-<number>" removed). STAGE1_EXCLUDE_RESERVED=0 disables this.
reserved_files = sorted(glob.glob(os.path.join(path, "eval-set-*", "reserved.json")))
reserved_tasks, reserved_repos = set(), set()
if os.environ.get("STAGE1_EXCLUDE_RESERVED", "1") == "1":
    for reserved_file in reserved_files:
        reserved = json.load(open(reserved_file))
        reserved_tasks.update(reserved.get("terminal_lego", {}).get("tasks", []))
        reserved_repos.update(reserved.get("swe", {}).get("repos", []))
def is_reserved(r):
    if r["task"] in reserved_tasks:
        return True
    return r["source"].startswith("swe-rebench") and r["task"].rsplit("-", 1)[0] in reserved_repos
before_reserved = len(rows)
rows = [r for r in rows if not is_reserved(r)]
print("reserved eval sets", [os.path.relpath(f, path) for f in reserved_files], "tasks", len(reserved_tasks),
      "repos", len(reserved_repos), "excluded", before_reserved - len(rows))
train = [r for r in rows if r["split"] == "train"]
val = [r for r in rows if r["split"] == "validation"]
# STAGE1_TRAIN_PER_SOURCE=N / STAGE1_VAL_PER_SOURCE=M: per-source quotas in index
# order, sources interleaved so a non-shuffled dataloader alternates sources. When a
# source has fewer than M audited validation tasks (Full audits cover train only),
# the held-out set is topped up with the next audited train tasks after the
# training quota, so held-out and training never overlap.
train_quota = int(os.environ.get("STAGE1_TRAIN_PER_SOURCE", "0"))
val_quota = int(os.environ.get("STAGE1_VAL_PER_SOURCE", "0"))
val_from_train = 0
if train_quota > 0:
    per_train, per_val = [], []
    for src in sources:
        src_train = [r for r in train if r["source"] == src]
        src_val = [r for r in val if r["source"] == src]
        chosen = src_train[:train_quota]
        held = src_val[:val_quota] if val_quota > 0 else src_val
        if val_quota > 0 and len(held) < val_quota:
            extra = src_train[train_quota:train_quota + val_quota - len(held)]
            val_from_train += len(extra); held = held + extra
        per_train.append(chosen); per_val.append(held)
        print("source", src, "train", len(chosen), "held-out", len(held), "(audited train pool", len(src_train), ")")
    train = [r for group in itertools.zip_longest(*per_train) for r in group if r is not None]
    val = [r for group in itertools.zip_longest(*per_val) for r in group if r is not None]
elif slice_n > 0:
    train = train[:slice_n]
# Unpack only the selected tasks from runtime-v1.tar.gz when the repo is packed.
needed = {}
for r in train + val:
    if not os.path.isdir(os.path.join(path, r["task_dir"])):
        batch_root = r["task_dir"].rsplit("/runtime-v1/", 1)[0]
        needed.setdefault(batch_root, set()).add(r["task_dir"].rsplit("/", 1)[1])
for batch_root, tasks in needed.items():
    archive = os.path.join(path, batch_root, "runtime-v1.tar.gz")
    with tarfile.open(archive) as tf:
        members = [m for m in tf if m.name.split("/")[1:2] and m.name.split("/")[1] in tasks]
        tf.extractall(os.path.join(path, batch_root), members=members, filter="data")
    print("unpacked", len(tasks), "tasks from", os.path.relpath(archive, path))
import re
from collections import Counter
# Harbor pulls task.toml `docker_image` from a registry and skips
# environment/Dockerfile unless force_build is set. Two dataset patterns make that
# wrong, so the alias is stripped and Harbor builds the Dockerfile instead:
#   alias       Terminal-Lego keeps `terminal-lego/<id>:latest`, which is not pullable
#               (prefixes in STAGE1_STRIP_IMAGE_PREFIXES).
#   base-image  docker_image equals the Dockerfile's FROM, i.e. it names the bare
#               base image and the Dockerfile's extra layers (swe-rebench installs
#               pytest-json-ctrf there, which the verifier's `pytest --ctrf` needs)
#               would never be applied. STAGE1_KEEP_BASE_IMAGE=1 disables this.
strip_prefixes = tuple(p for p in os.environ.get("STAGE1_STRIP_IMAGE_PREFIXES", "terminal-lego/").split() if p)
keep_base = os.environ.get("STAGE1_KEEP_BASE_IMAGE") == "1"
def norm(image):
    for prefix in ("docker.io/library/", "docker.io/"):
        if image.startswith(prefix):
            return image[len(prefix):]
    return image
stripped = Counter()
for name, subset in (("train", train), ("validation", val)):
    root = os.path.join(out, f"tasks-{name}")
    shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
    for i, r in enumerate(subset):
        # preprocess sorts task dirs by name; with per-source quotas an ordinal
        # prefix keeps the interleaved order (otherwise every epoch runs one source
        # after the other, as pipe-r6's steps 1-5 were all swe-rebench).
        prefix = f"{i:04d}__" if train_quota > 0 else ""
        dst = os.path.join(root, f"{prefix}{r['source']}__{r['task']}")
        shutil.copytree(os.path.join(path, r["task_dir"]), dst)
        toml_path = os.path.join(dst, "task.toml")
        dockerfile = os.path.join(dst, "environment", "Dockerfile")
        text = open(toml_path).read()
        m = re.search(r'^docker_image\s*=\s*"([^"]+)"\s*$', text, re.M)
        if not (m and os.path.exists(dockerfile)):
            continue
        image = m.group(1)
        base = re.search(r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)", open(dockerfile).read(), re.M | re.I)
        if image.startswith(strip_prefixes):
            reason = "alias"
        elif base and norm(base.group(1)) == norm(image) and not keep_base:
            reason = "base-image"
        else:
            continue
        open(toml_path, "w").write(text[: m.start()] + f"# docker_image {image} removed by 10_data.sh ({reason}); built from environment/Dockerfile\n" + text[m.end():])
        stripped[f"{r['source']}:{reason}"] += 1
    print(name, len(subset), root)
print("docker_image stripped", dict(stripped))
json.dump({"repo": repo, "slice": slice_n, "sources": sources, "require_audit": require_audit, "audit_dropped": before_audit - len(rows),
           "audit_sidecar_merged": merged, "reserved_excluded": before_reserved - len(rows), "train_per_source": train_quota, "val_per_source": val_quota, "val_from_train": val_from_train, "train": [r["task"] for r in train], "validation": [r["task"] for r in val],
           "difficulty": {d: sum(1 for r in train if r.get("difficulty") == d) for d in ("easy", "medium", "hard")}},
          open(os.path.join(out, "selection.json"), "w"), indent=1)
PY
  cat "${STAGE_DIR}/stage1-select.log"
  (cd "${REPO_ROOT}" && "${LANE_PY}" -m uni_agent.tasks.harbor.preprocess --task-root "${S1}/tasks-train" \
     --local-save-dir "${S1}/train") > "${STAGE_DIR}/preprocess-stage1-train.log" 2>&1
  (cd "${REPO_ROOT}" && "${LANE_PY}" -m uni_agent.tasks.harbor.preprocess --task-root "${S1}/tasks-validation" \
     --local-save-dir "${S1}/validation") > "${STAGE_DIR}/preprocess-stage1-val.log" 2>&1
  TRAIN_PARQUET="${S1}/train/harbor_tasks-train.parquet"
  FULL_PARQUET="${S1}/validation/harbor_tasks-validation.parquet"   # held-out for TEST_FILE
  echo "${TRAIN_PARQUET}" > "${STAGE_DIR}/train-parquet.txt"
  echo "${FULL_PARQUET}" > "${STAGE_DIR}/full-parquet.txt"
  cp "${S1}/selection.json" "${STAGE_DIR}/selection.json"
  ROWS=$("${LANE_PY}" -c "import pandas as pd,sys; print(len(pd.read_parquet(sys.argv[1])))" "${TRAIN_PARQUET}")
  mark_passed; record passed "{\"dataset\":\"stage1\",\"train_parquet\":\"${TRAIN_PARQUET}\",\"rows\":${ROWS},\"slice\":${STAGE1_SLICE}}"
  log "passed: stage1 slice=${STAGE1_SLICE} -> ${TRAIN_PARQUET} (${ROWS} rows); held-out ${FULL_PARQUET}"
  exit 0
fi

FULL_PARQUET="${DATA_DIR}/harbor_terminal-bench_terminal-bench-2-1.parquet"
if [[ ! -f "${FULL_PARQUET}" ]]; then
  (cd "${REPO_ROOT}" && "${LANE_PY}" -m uni_agent.tasks.harbor.preprocess --dataset-ref "${TB_DATASET_REF}" \
     --local-save-dir "${DATA_DIR}" --max-instances "${MAX_INSTANCES}") > "${STAGE_DIR}/preprocess-full.log" 2>&1
fi
TASK_ROOT="${DATA_DIR}/harbor/terminal-bench_terminal-bench-2-1/terminal-bench-2-1"
if [[ "${TASK_FILTER}" == easy ]]; then
  E="${DATA_DIR}/tb21-easy-tasks"; rm -rf "${E}"; mkdir -p "${E}"
  for t in ${EASY_TASKS}; do cp -r "${TASK_ROOT}/${t}" "${E}/${t}"; done   # preprocess ignores symlinks
  (cd "${REPO_ROOT}" && "${LANE_PY}" -m uni_agent.tasks.harbor.preprocess --task-root "${E}" \
     --local-save-dir "${DATA_DIR}/easy") > "${STAGE_DIR}/preprocess-easy.log" 2>&1
  TRAIN_PARQUET="${DATA_DIR}/easy/harbor_tb21-easy-tasks.parquet"
else
  TRAIN_PARQUET="${FULL_PARQUET}"
fi
echo "${TRAIN_PARQUET}" > "${STAGE_DIR}/train-parquet.txt"
echo "${FULL_PARQUET}" > "${STAGE_DIR}/full-parquet.txt"
ROWS=$("${LANE_PY}" -c "import pandas as pd,sys; print(len(pd.read_parquet(sys.argv[1])))" "${TRAIN_PARQUET}")
grep -h -E "^difficulty" "${TASK_ROOT}"/*/task.toml | sort | uniq -c > "${STAGE_DIR}/difficulty-histogram.txt" || true
mark_passed; record passed "{\"train_parquet\":\"${TRAIN_PARQUET}\",\"rows\":${ROWS},\"filter\":\"${TASK_FILTER}\"}"
log "passed: ${TRAIN_PARQUET} (${ROWS} rows)"
