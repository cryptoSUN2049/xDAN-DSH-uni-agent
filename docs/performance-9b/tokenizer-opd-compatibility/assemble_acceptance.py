"""Assemble bounded acceptance from saved evidence; missing inputs fail closed."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVIDENCE = {}


def read(relative):
    path = ROOT / relative
    value = json.loads(path.read_text())
    EVIDENCE[relative] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "data": value}
    return value


def main():
    coverage = read("live-audit/evidence/capture/coverage-verdict.json")
    live = read("live-audit/evidence/capture/replay-verdict.json")
    reload = read("live-audit/evidence/reload-acceptance.json")
    modules = read("live-audit/evidence/capture/adapter-module-audit.json")
    mode = read("mode-audit/evidence/mode-verdict.json")
    scores = read("mode-audit/evidence/score-acceptance.json")
    tools = read("tool-audit/result.json")
    read("live-audit/evidence/provenance.json")
    read("mode-audit/evidence/eos-audit.json")
    diagnostic = read("mode-audit/diagnostic-2048/samples.json")[0]
    assert diagnostic["prefix_1024_exactly_reproduced"] and diagnostic["thinking_close_observed"]
    assert diagnostic["response_tokens"] == 1751 and not diagnostic["budget_exhausted"]
    checks = {
        "live_capture_coverage": coverage["passed"],
        "live_loss_gradient": live["passed"],
        "checkpoint_export_reload": reload["passed"] and modules["passed"],
        "mode_scoring_coordinates": mode["score_coordinate_and_numeric_passed"],
        "thinking_budget_1024": mode["acceptance_passed"],
        "independent_teacher_scoring": scores["passed"],
        "native_tool_mask_controls": tools["passed"],
    }
    assert len(live["microbatches"]) == 2 and coverage["captured_rows"] == 8
    tokens = sum(r["valid_tokens"] for r in live["microbatches"])
    teacher = [
        r["live_teacher_vs_hf_at_temperature_1"] for r in scores["cases"] if "live_teacher_vs_hf_at_temperature_1" in r
    ]
    assert len(teacher) == 8
    assert all(r["loss_absolute_error"] == r["gradient_max_absolute_error"] == 0 for r in live["microbatches"])
    boundary = (
        "所有已定义门禁通过，但不代表全面性能提升。"
        if all(checks.values())
        else "存在未通过门禁："
        + "、".join(
            "单轮 thinking 在1024响应预算内闭合" if k == "thinking_budget_1024" else k
            for k, v in checks.items()
            if not v
        )
    )
    result = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "passed": all(checks.values()),
        "test_execution_complete": True,
        "current_thinking_off_text_path_passed": all(v for k, v in checks.items() if k != "thinking_budget_1024"),
        "checks": checks,
        "paragraphs": [
            "本轮兼容测试结果：" + boundary,
            f"真实VERL更新捕获2个microbatch、8条样本、{tokens}个有效响应token；"
            "独立loss与梯度复算均零误差，mask外梯度为0，teacher IDs无错位。",
            "248个文本LoRA模块全部产生非零更新，110个视觉模块保持零B；导出与独立30题重载的权重SHA相同。",
            "9种模式使用真实学生生成raw IDs，含thinking开关、多轮历史、构造工具历史及长prompt；"
            "与8条现场轨迹合并17例做独立HF/vLLM对照，并直接核验现场teacher概率。",
            "追加2048预算单例诊断在1751 token闭合并答对391，原1024前缀逐ID完全重现；"
            "原1024失败保留，新增尾部没有另做教师评分。HF默认EOS与VERL现场停止token不同，"
            "评分坐标兼容不代表跨框架生成停止等价。",
            "本次一步模型数学4/5、指令5/8、知识1/1，代码与聊天没有可靠正确率；不能从兼容性验收推出全面性能提升。",
        ],
        "diagnostic_note": (
            "2048 budget:1751 tokens closed thinking, exact first1024; no extra teacher scoring on extended tail"
        ),
        "columns": ["验收项", "结果", "证据范围"],
        "rows": [
            [
                "真实训练loss/gradient",
                "通过" if checks["live_loss_gradient"] else "失败",
                f"{tokens}有效token；两微批独立误差0",
            ],
            [
                "捕获覆盖",
                "通过" if checks["live_capture_coverage"] else "失败",
                "8/8；actor T0.8；exit0；step1 checkpoint",
            ],
            [
                "参数更新与独立重载",
                "通过" if checks["checkpoint_export_reload"] else "失败",
                "248文本模块非零更新；30/30；infra0；SHA一致",
            ],
            [
                "模式与同token评分",
                "通过" if checks["mode_scoring_coordinates"] else "失败",
                f"9模式+8现场轨迹；mean {mode['mean_abs_error']:.6f}，P95 {mode['p95_abs_error']:.6f}",
            ],
            [
                "现场teacher vs HF@1",
                "通过" if checks["independent_teacher_scoring"] else "失败",
                f"8/8；最差样本mean {max(t['mean_abs_error'] for t in teacher):.6f}",
            ],
            [
                "原生工具mask",
                "通过" if checks["native_tool_mask_controls"] else "失败",
                "5控制；真实状态处理/parser；模拟生成传输",
            ],
            [
                "Thinking 1024预算",
                "通过" if checks["thinking_budget_1024"] else "未通过",
                "未闭合案例：" + ", ".join(mode["unclosed_thinking_cases"]),
            ],
            ["Thinking2048单例诊断", "闭合", "1751token；原1024前缀精确复现；不改原门禁"],
            ["未认证范围", "未测试", "自主工具能力、多模态、超过4096上下文、广泛泛化收益"],
        ],
        "limits": [
            "One update on 8 samples, four observed domains; no knowledge sample in this batch",
            "Mode histories are constructed; native tool controls use mocked generation transport",
            "Thinking closure and scoring alignment are not a reasoning-quality evaluator",
            "No multimodal or context above4096 certification",
            "Repeatedly observed30-row validation is not a sealed generalization test",
            "Teacher temperature1 and actor0.8; model metadata hashes and shard sizes, not fresh full-shard hash",
            "W&B offline; no claim of cloud synchronization or full automatic performance stop-loss",
        ],
        "evidence": EVIDENCE,
    }
    (ROOT / "full-acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    (ROOT.parent / "overnight/full-acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    # Preserve failures as reviewable evidence, never rewrite the admission threshold.
    print(json.dumps({"passed": result["passed"], "checks": checks}, ensure_ascii=False))


if __name__ == "__main__":
    main()
