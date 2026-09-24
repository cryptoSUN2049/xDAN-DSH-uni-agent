#!/usr/bin/env python3
"""Render a local, dependency-free OPD report. Never fabricate absent results.

Run: python3 report.py [--root DIRECTORY] [--output FILE]
Inputs (all optional; missing inputs are explicitly shown):
state.json: {stages: [{name,status,reason,started_at,finished_at}], models: [...]}.
  stages/models also accept dictionaries keyed by stage/model ID.
dataset-manifest.json: {domains: [{domain,count,source,split}], ...}.
compatibility/report.json: arbitrary JSON; report preserves its original findings.
models/<id>/eval.json: {model: {id,path,revision,role}, status, reason,
  domains: [{domain,count,scored,skipped,infra,score,output_tokens_mean,
             truncated,truncated_count,truncated_rate}], overall: {...},
  score_definition, budget, dataset_revision, paired_comparison}.
  score is a fraction in [0,1]; absent values display as unavailable, never zero.
  count is attempted/expected (define in count_definition), scored is graded count.
  domains also accepts a dictionary. overall is supplied, never inferred from
  potentially heterogeneous scores. Per-domain means are not averaged blindly.
train-metrics.jsonl: objects with model_id, step, loss, grad_norm,
  output_tokens_mean, truncated_rate, effective_group_ratio (any may be absent).
Additional fields are retained in expandable raw records.
"""

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path

STATUSES = {
    "pending": "待执行",
    "running": "运行中",
    "failed": "失败",
    "complete": "完成",
    "blocked": "受阻",
    "skipped": "跳过",
}


def esc(value):
    return html.escape(str(value), quote=True)


def val(value):
    if value is None:
        return "—（未提供）"
    if isinstance(value, (dict, list)):
        return esc(json.dumps(value, ensure_ascii=False))
    return esc(value)


def status(value):
    value = value or "pending"
    css = value if value in STATUSES else "pending"
    return f'<span class="badge {css}">{esc(STATUSES.get(value, value))}</span>'


def read_json(path, issues):
    if not path.exists():
        return None
    try:
        obj = json.loads(path.read_text())
        if not isinstance(obj, dict):
            raise ValueError("根节点应为 JSON 对象")
        return obj
    except (OSError, ValueError) as exc:
        issues.append(f"{path.name}: {exc}")
        return None


def records(data, key):
    if isinstance(data, dict):
        return [{key: name, **(item if isinstance(item, dict) else {"value": item})} for name, item in data.items()]
    return [item for item in (data or []) if isinstance(item, dict)]


def raw(title, obj):
    return (
        f"<details><summary>{esc(title)}</summary><pre>"
        f"{esc(json.dumps(obj, ensure_ascii=False, indent=2))}</pre></details>"
    )


def table(headers, rows):
    if not rows:
        return '<p class="muted">尚无记录。</p>'
    return (
        '<div class="scroll"><table><thead><tr>'
        + "".join(f"<th>{esc(h)}</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
        + "</tbody></table></div>"
    )


def score_rows(data):
    rows = []
    groups = records(data.get("domains"), "domain")
    if isinstance(data.get("overall"), dict):
        groups.insert(0, {**data["overall"], "domain": "全局（输入报告口径）"})
    for item in groups:
        rows.append(
            [
                val(item.get(key))
                for key in (
                    "domain",
                    "count",
                    "scored",
                    "skipped",
                    "infra",
                    "score",
                    "output_tokens_mean",
                    "output_tokens_median",
                    "truncated_count",
                    "truncated_rate",
                )
            ]
        )
    return rows


def render(root):
    issues = []
    state = read_json(root / "state.json", issues) or {}
    manifest = read_json(root / "dataset-manifest.json", issues)
    compat = read_json(root / "compatibility/report.json", issues)
    pieces = [
        "<h1>9B 多领域单教师 OPD · 训练与评测报告</h1>",
        '<p class="muted">生成于 '
        + esc(datetime.now(timezone.utc).isoformat(timespec="seconds"))
        + " · UTC · 静态快照，需重新运行脚本更新。</p>",
        '<p class="notice">目标：27B 教师指导 9B 学生，覆盖多个领域。'
        "这是多领域单教师 OPD，不是多教师 MOPD。静态教师答案用于 SFT 时，"
        "也不等于学生在线采样的 OPD。完成状态以落盘证据为准；缺失指标不记作零分。</p>",
        '<p class="notice">数据质量复审：初始160/40候选集发现错误答案和不完整题目，旧结果仅作诊断。'
        "正式结论需使用冻结的修订数据，不能将候选集称为已验收高质量数据。</p>",
    ]
    acceptance = read_json(root / "full-acceptance.json", issues)
    if acceptance:
        pieces.append("<h2>补充完整验收 · 真实训练与模式矩阵</h2>")
        pieces.extend("<p>" + esc(paragraph) + "</p>" for paragraph in acceptance.get("paragraphs", []))
        pieces.append(
            table(acceptance.get("columns", []), [[val(cell) for cell in row] for row in acceptance.get("rows", [])])
        )
        pieces.append(raw("完整验收证据与范围", acceptance))
    conclusion = read_json(root / "final-analysis.json", issues)
    if conclusion:
        pieces.append("<h2>实验结论</h2>")
        pieces.extend("<p>" + esc(paragraph) + "</p>" for paragraph in conclusion.get("paragraphs", []))
        pieces.append(
            table(conclusion.get("columns", []), [[val(cell) for cell in row] for row in conclusion.get("rows", [])])
        )
    pieces.append("<h2>执行状态</h2>")
    stages = records(state.get("stages"), "name")
    pieces.append(
        table(
            ["阶段", "状态", "原因 / 说明", "开始", "结束"],
            [
                [
                    val(s.get("name")),
                    status(s.get("status")),
                    val(s.get("reason")),
                    val(s.get("started_at")),
                    val(s.get("finished_at")),
                ]
                for s in stages
            ],
        )
    )
    if not state:
        pieces.append("<p>尚未提供 state.json；不能据此判断训练是否已经启动。</p>")
    contract = root / "experiment-contract.md"
    if contract.exists():
        pieces.append(
            "<details><summary>实际实验配置与成功条件</summary><pre>" + esc(contract.read_text()) + "</pre></details>"
        )
    history = read_json(root / "history.json", issues)
    if history:
        pieces.append("<h2>失败与修订记录</h2>" + raw("保留的失败证据及处理", history))
    pieces.append("<h2>数据版本与领域分布</h2>")
    if manifest is None:
        pieces.append("<p>dataset-manifest.json 尚未落盘，数据配比待确认。</p>")
    else:
        pieces.append(
            table(
                ["领域", "条数", "来源", "切分"],
                [
                    [val(d.get(k)) for k in ("domain", "count", "source", "split")]
                    for d in records(manifest.get("domains"), "domain")
                ],
            )
        )
        pieces.append(raw("完整数据清单与版本", manifest))
    for filename, title in [
        ("environment.json", "运行环境证据"),
        ("run-provenance.json", "运行命令、源码指纹与 W&B 离线记录"),
        ("quality-review-80.json", "逐题质量复审与排除依据"),
        ("sampling-audit.json", "实际 rollout 领域分布（生成记录，不等于更新完成）"),
        ("training-completion-audit.json", "训练完成核验：实际步骤、有限梯度与保存版本"),
        ("final-weight-audit.json", "最终权重与实际评测加载身份核验"),
        ("final-evaluation-audit.json", "七版本210条输出身份与重评分核验"),
        ("deep-compatibility.json", "补充兼容验收：原生源码、2736token评分与loss梯度"),
    ]:
        evidence = read_json(root / filename, issues)
        if evidence is not None:
            pieces.append(raw(title, evidence))
    pieces.append("<h2>教师 / 学生兼容验收</h2>")
    if compat is None:
        pieces.append("<p>尚无 compatibility/report.json，不能宣称运行兼容性通过。</p>")
    else:
        pieces.append(status(compat.get("status")))
        pieces.append(raw("短序列 token 与教师评分兼容证据", compat))
    pieces.append(
        "<h2>各模型评测</h2><p>score 按输入定义展示（约定为 0–1）；"
        "必须同时核对有效评分数、跳过数与基础设施失败数。"
        "不同数据版本或预算的分数不可直接比较。</p>"
    )
    for folder in ("adapters-smoke", "adapters"):
        checkpoint_manifest = read_json(root / folder / "manifest.json", issues)
        if checkpoint_manifest:
            pieces.append(raw(f"Checkpoint 完整性与非零更新验收：{folder}", checkpoint_manifest))
    paths = sorted((root / "models").glob("*/eval.json"))
    seen = set()
    for path in paths:
        data = read_json(path, issues)
        if data is None:
            continue
        seen.add(path.parent.name)
        model = data.get("model") or {"id": path.parent.name}
        pieces.extend(
            [
                f"<h3>{esc(path.parent.name)}</h3>",
                status(data.get("status")),
                f"<p>{val(data.get('reason'))}</p>",
                raw(
                    "模型身份",
                    {
                        "model": model,
                        "model_path": data.get("model_path"),
                        "adapter_path": data.get("adapter_path"),
                        "adapter_weights_sha256": data.get("adapter_weights_sha256"),
                        "adapter_reload_verified": data.get("adapter_reload_verified"),
                    },
                ),
            ]
        )
        pieces.append(
            table(
                [
                    "范围",
                    "总数",
                    "有效评分数",
                    "跳过",
                    "基础设施失败",
                    "得分",
                    "平均输出 token",
                    "输出中位数",
                    "截断数",
                    "截断率",
                ],
                score_rows(data),
            )
        )
        pieces.append(raw("完整评测证据、预算和配对分析", data))
    for model in records(state.get("models"), "id"):
        if str(model.get("id")) not in seen:
            pieces.append(f"<h3>{val(model.get('id'))}</h3><p>尚无独立评测结果。</p>")
            pieces.append(raw("模型计划 / 身份", model))
    if not paths:
        pieces.append("<p>尚无 models/&lt;id&gt;/eval.json。当前没有可报告的新模型分数。</p>")
    metrics = []
    metric_path = root / "train-metrics.jsonl"
    if metric_path.exists():
        for line_no, line in enumerate(metric_path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError("指标行应为对象")
                metrics.append(item)
            except ValueError as exc:
                issues.append(f"train-metrics.jsonl 第 {line_no} 行: {exc}")
    pieces.append(
        "<h2>训练观测</h2><p>有效 RL 组比例仅适用于依赖任务奖励的组内优势；"
        "纯 OPD 应检查蒸馏信号、梯度与行为指标，不能套用 RL 零优势止损条件。</p>"
    )
    pieces.append(
        table(
            ["模型", "步数", "损失", "梯度范数", "平均输出 token", "截断率", "有效 RL 组比例"],
            [
                [
                    val("不适用（纯 OPD）" if k == "effective_group_ratio" and m.get(k) is None else m.get(k))
                    for k in (
                        "model_id",
                        "step",
                        "loss",
                        "grad_norm",
                        "output_tokens_mean",
                        "truncated_rate",
                        "effective_group_ratio",
                    )
                ]
                for m in metrics
            ],
        )
    )
    if metrics:
        pieces.append(raw("完整训练指标", metrics))
    pieces.append(
        "<h2>分析与结论边界</h2><ul><li>只有同一固定验证集、相同预算与一致评分规则，"
        "才能比较教师、原版学生和训练后学生。</li><li>loss 下降不证明解题能力提升；"
        "需分域评测与 token、截断、超时行为一起验收。</li><li>教师更大不代表在每个领域更强；"
        "本报告不会从缺失数据推断收益或失败。</li></ul>"
    )
    notes = root / "analysis-notes.md"
    if notes.exists():
        pieces.append(
            "<details><summary>逐题分析、证据边界与补齐计划</summary><pre>"
            + esc(notes.read_text())
            + "</pre></details>"
        )
    if state.get("analysis"):
        pieces.append(raw("当前证据分析", state["analysis"]))
    if issues:
        pieces.append("<h2>报告输入错误</h2>" + raw("需要修复的输入（未静默忽略）", issues))
    return (
        """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>9B 多领域单教师 OPD 报告</title><style>
body{font:16px/1.7 system-ui,sans-serif;color:#dbe6fa;background:#0d1424;margin:0;padding:32px}
main{max-width:1320px;margin:auto}h1{font-size:30px}h2{border-bottom:1px solid #32415b;padding-top:24px}
.muted{color:#a9b8d0}.notice{background:#182b46;border-left:4px solid #75a6ff;padding:16px}
.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}
td,th{padding:10px;text-align:left;border:1px solid #32415b}
th{background:#1c2940}.badge{display:inline-block;padding:2px 10px;border-radius:20px;background:#35425a}
.running{background:#164c7d}.failed,.blocked{background:#7c2935}.complete{background:#176049}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px;background:#151f32;padding:16px}
summary{cursor:pointer;color:#9fc2ff}details{margin:12px 0}@media(max-width:600px){body{padding:16px}h1{font-size:24px}}
</style><main>"""
        + "\n".join(pieces)
        + "</main></html>"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    target = args.output or args.root / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(render(args.root), encoding="utf-8")
    temporary.replace(target)
    print(target)


if __name__ == "__main__":
    main()
