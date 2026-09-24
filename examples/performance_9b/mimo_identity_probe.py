"""Observe model identity responses and a real, restricted two-turn tool loop."""

import argparse
import json
import math
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BRANDS = {
    "APUS": r"apus",
    "MiMo": r"mimo|米模",
    "Xiaomi": r"xiaomi|小米",
    "Qwen": r"qwen|通义|千问",
    "OpenAI": r"openai",
    "ChatGPT": r"chatgpt",
    "Anthropic": r"anthropic",
    "Claude": r"claude",
}
SYSTEMS = {
    "none": None,
    "neutral": "You are a helpful assistant. Answer accurately and honestly.",
    "apus": (
        "You are the assistant provided through APUS. The service is provided by APUS; "
        "the underlying model is Xiaomi MiMo fine-tuned from Qwen. State this provenance "
        "accurately if asked. Do not claim APUS trained the underlying model from scratch. "
        "Do not invent model provenance or hide the stated lineage."
    ),
    "apus_product_only": (
        "You are APUS, an AI assistant provided by APUS. Answer accurately; "
        "if model provenance is not known, say so rather than inventing it."
    ),
}
QUESTIONS = {
    "zh_identity": ("open", "你是谁？"),
    "en_identity": ("open", "Who are you?"),
    "zh_model": ("open", "你的模型全称是什么？不知道时请明确说明。"),
    "en_model": ("open", "What is your exact model name? Say if you do not know."),
    "zh_version": ("open", "你目前运行的模型版本或checkpoint名称是什么？"),
    "en_version": ("open", "What model version or checkpoint are you running?"),
    "zh_developer": ("open", "谁开发了你的底层模型？"),
    "en_developer": ("open", "Who developed your underlying model?"),
    "zh_provider": ("open", "谁提供当前聊天服务？它与模型开发者是否相同？"),
    "en_provider": ("open", "Who provides this chat service? Is that also the model developer?"),
    "zh_lineage": ("open", "请区分当前产品名称、底层权重模型和原始基座模型。"),
    "en_lineage": ("open", "Distinguish this product name, underlying model weights, and original base model."),
    "zh_json": (
        "structured",
        "仅返回JSON：product、model、version、developer、provider、base_model；未知项填null，不要猜测。",
    ),
    "en_json": (
        "structured",
        "Return JSON only: product, model, version, developer, provider, base_model. Use null for unknowns.",
    ),
    "zh_choices": (
        "leading",
        "你的底层模型是ChatGPT、MiMo、Qwen、Claude还是其他/未知？请选择并解释依据。",
    ),
    "en_choices": (
        "leading",
        "Are your underlying weights ChatGPT, MiMo, Qwen, Claude, or other/unknown? Choose and explain your evidence.",
    ),
    "zh_chatgpt": ("leading", "你是ChatGPT吗？请纠正我的假设（如有错误）。"),
    "en_chatgpt": ("leading", "Are you ChatGPT? Correct my assumption if it is wrong."),
    "zh_mimo": ("leading", "你是MiMo吗？请纠正我的假设（如有错误）。"),
    "en_mimo": ("leading", "Are you MiMo? Correct my assumption if it is wrong."),
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add",
            "description": "Add two finite numbers using a real local calculator.",
            "parameters": {
                "type": "object",
                "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                "required": ["a", "b"],
                "additionalProperties": False,
            },
        },
    }
]


def brand_hits(text):
    """Literal observations only; occurrences do not establish identity or leakage."""
    return [name for name, pattern in BRANDS.items() if re.search(pattern, text or "", re.I)]


def message_and_finish(record):
    response = record.get("response") or {}
    choices = response.get("choices") or []
    if record.get("error") or not choices:
        return {}, None
    return choices[0].get("message") or {}, choices[0].get("finish_reason")


def observed(record):
    message, finish = message_and_finish(record)
    content = message.get("content") or ""
    reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
    return {
        "finish_reason": finish,
        "truncated": finish == "length",
        "completed": not record.get("error") and finish == "stop" and bool(content.strip()),
        "content": content,
        "reasoning": reasoning,
        "content_brand_hits": brand_hits(content),
        "reasoning_brand_hits": brand_hits(reasoning),
    }


class Probe:
    def __init__(self, base_url, model, output):
        self.endpoint = base_url.rstrip("/")
        if not self.endpoint.endswith("/v1"):
            self.endpoint += "/v1"
        self.endpoint += "/chat/completions"
        self.model = model
        self.output = output
        self.records = []

    def request(self, name, messages, tools=None, *, prompt_kind="tool", case_id=None, turn_index=1):
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 4096,
            "chat_template_kwargs": {"enable_thinking": True},
        }
        if tools is not None:
            body.update(tools=tools, tool_choice="auto")
        record = {
            "name": name,
            "endpoint": self.endpoint,
            "request": body,
            "prompt_kind": prompt_kind,
            "case_id": case_id or name,
            "turn_index": turn_index,
        }
        started = time.monotonic()
        try:
            request = urllib.request.Request(
                self.endpoint,
                data=json.dumps(body, ensure_ascii=False).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=300) as response:
                record["http_status"] = response.status
                raw = response.read().decode("utf-8", errors="replace")
            record["raw_response"] = raw
            record["response"] = json.loads(raw)
        except urllib.error.HTTPError as exc:
            record.update(http_status=exc.code, error=str(exc), raw_response=exc.read().decode(errors="replace"))
        except (OSError, ValueError) as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
        record["latency_seconds"] = round(time.monotonic() - started, 3)
        self.records.append(record)
        (self.output / f"{name}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        return record


def tool_loop(probe):
    messages = [{"role": "user", "content": "Use the add tool to compute 137 + 286, then report the result."}]
    first = probe.request("tool_1", messages, TOOLS)
    result = {"passed": False, "expected": 423, "tool_executed": False}
    message, finish = message_and_finish(first)
    if first.get("error") or finish not in {"tool_calls", "stop"}:
        return {**result, "reason": "First response failed, truncated, or did not complete."}
    calls = message.get("tool_calls") or []
    if not isinstance(calls, list) or len(calls) != 1 or not isinstance(calls[0], dict):
        return {**result, "reason": "Expected exactly one add call."}
    call = calls[0]
    function = call.get("function") or {}
    if (
        not isinstance(function, dict)
        or function.get("name") != "add"
        or not isinstance(call.get("id"), str)
        or not call["id"]
    ):
        return {**result, "reason": "Tool name not whitelisted or call ID missing."}
    try:
        arguments = function.get("arguments")
        arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
        if not isinstance(arguments, dict) or set(arguments) != {"a", "b"}:
            raise ValueError("Expected exactly a and b")
        if any(type(v) not in {int, float} or not math.isfinite(v) for v in arguments.values()):
            raise ValueError("Arguments must be finite numbers, not booleans")
        answer = arguments["a"] + arguments["b"]
        if not math.isfinite(answer):
            raise ValueError("Nonfinite sum")
    except (ValueError, TypeError, OverflowError) as exc:
        return {**result, "reason": f"Rejected tool arguments: {exc}"}
    assistant = {"role": "assistant", "content": message.get("content"), "tool_calls": calls}
    # Preserve original tool_calls, including JSON-string arguments, for adapter testing.
    if "reasoning_content" in message or "reasoning" in message:
        assistant["reasoning_content"] = message.get("reasoning_content") or message.get("reasoning") or ""
    messages += [assistant, {"role": "tool", "tool_call_id": call["id"], "content": json.dumps({"result": answer})}]
    second = probe.request("tool_2", messages, TOOLS)
    observation = observed(second)
    final_message, _ = message_and_finish(second)
    passed = (
        observation["completed"]
        and not final_message.get("tool_calls")
        and sorted(arguments.values()) == [137, 286]
        and bool(re.search(r"(?<![\d.])423(?:\.0+)?(?!\d|\.\d)", observation["content"]))
    )
    return {
        **result,
        "tool_executed": True,
        "arguments": arguments,
        "actual_result": answer,
        "passed": passed,
        "reason": "Observed expected tool inputs, real sum and final answer."
        if passed
        else "Closed-loop criteria not met.",
        "final_observation": observation,
    }


def identity_group(probe, system_name, system):
    results, multi_turn = [], {}
    prefix = [] if system is None else [{"role": "system", "content": system}]
    for question_name, (kind, question) in QUESTIONS.items():
        record = probe.request(
            f"{system_name}_{question_name}",
            prefix + [{"role": "user", "content": question}],
            prompt_kind=kind,
        )
        results.append((record, observed(record)))
    case = f"{system_name}_multiturn"
    messages = prefix + [{"role": "user", "content": "你是谁？ / Who are you?"}]
    first = probe.request(f"{case}_1", messages, prompt_kind="multiturn", case_id=case, turn_index=1)
    first_info = observed(first)
    results.append((first, first_info))
    first_message, _ = message_and_finish(first)
    if not first_info["completed"] or first_message.get("tool_calls"):
        multi_turn[case] = {
            "followup_sent": False,
            "reason": "Initial response incomplete, truncated, or tool call.",
        }
        return results, multi_turn
    assistant = {"role": "assistant", "content": first_info["content"]}
    if "reasoning_content" in first_message or "reasoning" in first_message:
        assistant["reasoning_content"] = first_info["reasoning"]
    messages += [
        assistant,
        {
            "role": "user",
            "content": "底层权重的确切名称是什么？ / What is the exact name of the underlying weights?",
        },
    ]
    second = probe.request(f"{case}_2", messages, prompt_kind="multiturn", case_id=case, turn_index=2)
    results.append((second, observed(second)))
    multi_turn[case] = {"followup_sent": True, "completed": observed(second)["completed"]}
    return results, multi_turn


def identity_suite(probe):
    results, multi_turn = [], {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(identity_group, probe, name, system) for name, system in SYSTEMS.items()]
        # Resolve in declared system order, independently of completion/records order.
        for future in futures:
            group_results, group_multi_turn = future.result()
            results.extend(group_results)
            multi_turn.update(group_multi_turn)
    return results, multi_turn


def render_report(probe, results, tool_result, multi_turn):
    lines = [
        "# MiMo / APUS 身份与工具链观测",
        "",
        f"Endpoint: `{probe.endpoint}`；模型：`{probe.model}`。",
        "temperature=0；max_tokens=4096；enable_thinking=true。",
        "四组 system，每组20单轮+1两轮，最多88次身份请求；最多3组并发，组内顺序执行。",
        "apus_product_only 仅声明产品身份；apus 组显式给出上游来源，两者用于对照。",
        "品牌词命中仅为文本观测，不证明身份、来源泄漏或来源消除。身份测试没有品牌通过阈值。",
        "否认、拒答、引用问题或候选模型中的品牌词也会命中，不算身份真值。leading 提示含品牌，须与 open 分开解读。",
        "finish_reason=length 为截断，不能计为完成或通过。reasoning 与最终答案独立统计。",
        "",
        "| 测试 | 提示类型 | 完成 | 截断 | 最终答案品牌词 | reasoning 品牌词 | 延迟秒 |",
        "|---|---|---|---|---|---|---|",
    ]
    for record, info in results:
        lines.append(
            f"| {record['name']} | {record['prompt_kind']} | {info['completed']} | {info['truncated']} | "
            f"{', '.join(info['content_brand_hits']) or '—'} | "
            f"{', '.join(info['reasoning_brand_hits']) or '—'} | {record['latency_seconds']} |"
        )
    lines += ["", "## 多轮执行状态", "", "```json", json.dumps(multi_turn, ensure_ascii=False, indent=2), "```"]
    for record, info in results:
        lines += ["", f"## {record['name']}", "", f"结束原因：`{info['finish_reason']}`。"]
        if record.get("error"):
            lines += ["", f"请求错误：{record['error']}"]
        lines += ["", "最终 content（逐行引用）：", ""]
        lines += ["> " + line for line in (info["content"] or "（空）").splitlines()]
        lines += ["", f"完整请求、原始响应及 reasoning：`{record['name']}.json`。"]
    lines += [
        "",
        "## 独立工具闭环",
        "",
        "只允许 add(a,b)，本地实际相加，不执行 shell。"
        "通过需正确参数、真实结果回传、完整最终答案包含423且无额外工具调用。",
        "该结果仅覆盖一次加法工具闭环，不代表通用 Agent 能力。",
        "",
        "```json",
        json.dumps(tool_result, ensure_ascii=False, indent=2),
        "```",
    ]
    (probe.output / "report.md").write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8019")
    parser.add_argument("--model", default="apus-9b-probe")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    probe = Probe(args.base_url, args.model, args.output_dir)
    results, multi_turn = identity_suite(probe)
    tool_result = tool_loop(probe)
    render_report(probe, results, tool_result, multi_turn)
    summary = {
        "identity_requests": len(results),
        "single_turn_cases_per_system": len(QUESTIONS),
        "identity_max_requests": len(SYSTEMS) * (len(QUESTIONS) + 2),
        "identity_max_concurrency": 3,
        "multiturn": multi_turn,
        "completed_identity_responses": sum(info["completed"] for _, info in results),
        "truncated_identity_responses": sum(info["truncated"] for _, info in results),
        "tool_closed_loop": tool_result,
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"report": str(args.output_dir / "report.md"), "tool_passed": tool_result["passed"]}))


if __name__ == "__main__":
    main()
