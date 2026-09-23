"""Pilot diagnostics, not benchmark-equivalent graders. Unscored != incorrect."""

import ast
import json
import re
from decimal import Decimal, InvalidOperation


def final_text(text):
    return text.rsplit("</think>", 1)[-1].strip()


def grade(domain, response, ground_truth, extra_info=None):
    text = final_text(response)
    extra = extra_info or {}
    result = {"status": "unscored", "score": None, "verifier": "not_available"}
    if domain == "math":
        matches = re.findall(r"\\boxed\{([^{}]+)\}", text)
        if matches:
            candidate = matches[-1]
        else:
            lines = [x.strip() for x in text.splitlines() if x.strip()]
            candidate = lines[-1] if lines else ""
            match = re.fullmatch(r"(?:The answer is\s*|Answer:\s*)?([-+]?\d+(?:\.\d+)?)[.!]?\s*", candidate, re.I)
            candidate = match.group(1) if match else ""
        try:
            expected = Decimal(str(ground_truth).strip())
        except InvalidOperation:
            return result
        try:
            score = Decimal(candidate.strip()) == expected
        except InvalidOperation:
            score = False
        return {"status": "scored", "score": float(score), "verifier": "strict_numeric_final_v1"}
    if domain in ("science", "knowledge_mcqa"):
        matches = re.findall(r"\\boxed\{\s*([A-J])\s*\}", text, re.I)
        if not matches:
            matches = re.findall(r"(?:answer|option|choice)\s*(?:is|:)\s*\(?([A-J])\)?\b", text, re.I)
        if not matches:
            matches = re.findall(r"(?:^|\n)\s*<\s*([A-J])\s*>\s*$", text, re.I)
        if not matches:
            matches = re.findall(r"option\s+selected\s*:\s*([A-J])\b", text, re.I)
        if not matches:
            matches = re.findall(r"^\s*\(?([A-J])\)?[.)]?\s*$", text, re.M)
        expected = str(ground_truth).strip().upper()
        if not re.fullmatch("[A-J]", expected):
            return result
        return {
            "status": "scored",
            "score": float(bool(matches) and matches[-1].upper() == expected),
            "verifier": "strict_mcqa_final_v1",
        }
    if domain in ("if", "instruction_following", "instruction"):
        instructions = extra.get("instruction_id_list")
        kwargs = extra.get("kwargs")
        if kwargs is None and extra.get("kwargs_json"):
            kwargs = json.loads(extra["kwargs_json"])
        if instructions is None:
            try:
                parsed = json.loads(ground_truth) if isinstance(ground_truth, str) else ground_truth
                instructions, kwargs = parsed["instruction_id_list"], parsed["kwargs"]
            except (KeyError, TypeError, ValueError):
                return result
        checks = []
        for instruction, args in zip(instructions, kwargs, strict=True):
            if instruction == "keywords:existence":
                checks.append(all(word.lower() in text.lower() for word in args["keywords"]))
            elif instruction == "keywords:forbidden_words":
                checks.append(all(word.lower() not in text.lower() for word in args["forbidden_words"]))
            elif instruction == "length_constraints:number_words":
                count = len(text.split())
                relation = args["relation"]
                if relation not in ("at least", "less than"):
                    return result
                checks.append(count >= args["num_words"] if relation == "at least" else count < args["num_words"])
            elif instruction == "detectable_format:json_format":
                try:
                    json.loads(text)
                    checks.append(True)
                except ValueError:
                    checks.append(False)
            elif instruction == "change_case:english_lowercase":
                checks.append(any(c.isalpha() for c in text) and text == text.lower())
            elif instruction == "change_case:english_uppercase":
                checks.append(any(c.isalpha() for c in text) and text == text.upper())
            elif instruction == "startend:end_checker":
                checks.append(text.rstrip().endswith(args["end_phrase"]))
            else:
                return result
        if checks:
            return {
                "status": "scored",
                "score": float(bool(text.strip()) and all(checks)),
                "verifier": "pilot_if_rules_v1_not_official_ifeval",
            }
        return result
    if domain == "code":
        blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.S)
        code = blocks[-1] if blocks else text
        try:
            ast.parse(code)
            syntax = bool(code.strip())
        except (SyntaxError, ValueError):
            syntax = False
        return {**result, "verifier": "no_isolated_execution", "python_syntax_valid": syntax}
    return result


def compute_score(data_source, solution_str, ground_truth, extra_info=None, **kwargs):
    result = grade(data_source, solution_str, ground_truth, extra_info)
    # VERL requires a numeric reward even in pure OPD. Never treat this placeholder as accuracy.
    return {
        "score": result["score"] if result["score"] is not None else 0.0,
        "scored": float(result["status"] == "scored"),
        "verifier": result["verifier"],
    }
