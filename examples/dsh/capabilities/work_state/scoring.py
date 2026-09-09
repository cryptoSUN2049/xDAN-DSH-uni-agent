"""Pure controller business scoring. Actor format/quality failures return zero."""

import json

MAX_OUTPUT_BYTES = 65536


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("nonfinite JSON number")


def _load(raw, expected_type):
    if not isinstance(raw, bytes) or len(raw) > MAX_OUTPUT_BYTES:
        raise ValueError("missing/non-bytes/oversized output")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    if type(value) is not expected_type:
        raise ValueError("wrong JSON root type")
    return value


def _configuration(task, config):
    truth = task["truth"]
    if task["family"] != "WS03":
        expected = truth["expected_config"]
        return set(config) == set(expected) and all(
            type(config[k]) is type(v) and config[k] == v for k, v in expected.items()
        )
    catalog = truth["catalog"]
    if set(config) != set(catalog) or any(not isinstance(v, str) or v not in catalog[k] for k, v in config.items()):
        return False
    selected = {k: catalog[k][v] for k, v in config.items()}
    if task["variant"] == 0:
        return (
            selected["database"]["transactions"] is True
            and selected["database"]["protocol"] == selected["cache"]["protocol"]
        )
    requirement = truth["requirements"]
    return (
        selected["encoder"]["format"] == selected["transport"]["format"] == requirement["format"]
        and selected["transport"]["region"] == selected["storage"]["region"] == requirement["region"]
        and selected["storage"]["retention"] >= requirement["minimum_retention"]
    )


def score_task(task: dict, outputs: dict[str, bytes]) -> dict:
    """Trust only controller task. Actual path/access/receipt audit remains external."""
    if task.get("schema") != "dsh.work-state-task.v1":
        raise ValueError("Unknown trusted task schema")
    errors = []
    checks = {"output_contract": False, "configuration": False, "plan_execution": False}
    if not isinstance(outputs, dict) or set(outputs) != set(task["result_paths"]):
        errors.append("Output paths must be exactly config.json and plan.json")
    else:
        checks["output_contract"] = True
    try:
        config = _load(outputs.get("config.json") if isinstance(outputs, dict) else None, dict)
        checks["configuration"] = _configuration(task, config)
        if not checks["configuration"]:
            errors.append("Configuration violates current task requirements")
    except (ValueError, UnicodeError, TypeError, RecursionError) as error:
        errors.append(f"Invalid config artifact: {error}")
    try:
        plan = _load(outputs.get("plan.json") if isinstance(outputs, dict) else None, list)
        truth = task["truth"]
        done = set(truth["completed"])
        valid = all(isinstance(action, str) for action in plan)
        if valid:
            for action in plan:
                if (
                    action in done
                    or action not in truth["dependencies"]
                    or not set(truth["dependencies"][action]) <= done
                ):
                    valid = False
                    break
                done.add(action)
        checks["plan_execution"] = valid and set(truth["required"]) <= done
        if not checks["plan_execution"]:
            errors.append("Unknown/repeated/out-of-order/incomplete workflow action")
    except (ValueError, UnicodeError, TypeError, RecursionError) as error:
        errors.append(f"Invalid plan artifact: {error}")
    reward = int(all(checks.values()))
    return dict(
        reward=reward,
        checks=checks,
        errors=errors,
        verified_progress=sum(checks[k] for k in ("configuration", "plan_execution")) / 2,
    )
