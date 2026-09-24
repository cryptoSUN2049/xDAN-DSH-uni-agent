"""Auditable selection flags; callers retain originals and decide disposition."""

import json
import re

from examples.performance_9b.quality import classify_teacher


def _metadata(raw):
    value = raw.get("metadata", {})
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def policy_flags(raw, normalized, source_id):
    """Flag known provenance/rights/held-out issues, never infer missing attestation."""
    flags = set()
    source = str(source_id).lower()
    teacher = classify_teacher(normalized.get("teacher_claimed"))
    evidence = normalized.get("teacher_evidence") or {}
    if teacher == "unknown":
        flags.add("unknown_teacher")
    if evidence.get("conflict") is True:
        flags.add("teacher_conflict")
    claims = [normalized.get("teacher_claimed")]
    claims.extend(c.get("value") for c in evidence.get("claims", []) if isinstance(c, dict))
    if (source == "codeflame" or source.startswith("codeflame/")) and any(
        isinstance(c, str) and re.search(r"(?<![a-z0-9])gemini[-_ ]?3\.1(?![0-9.])", c, re.I) for c in claims
    ):
        flags.add("excluded_gemini31")
    if source == "premium" or "fable-5-premium-v2" in source:
        flags.add("mixed_teacher_provenance_unresolved")
    if "helio" in source:
        flags.add("unknown_source_license")
    if "spreadsheet-rl" in source:
        flags.add("not_sft_source")
    metadata = _metadata(raw)
    for mapping in (raw, metadata):
        if mapping.get("model_attested") is False:
            flags.add("teacher_unattested")
        for key in ("source_split", "split"):
            split = str(mapping.get(key) or "").lower()
            if re.search(r"(?:^|[^a-z])(test|validation|valid|val|dev|eval|evaluation)(?:$|[^a-z])", split):
                flags.add("heldout_source")
        provenance = " ".join(
            str(mapping.get(k) or "") for k in ("source", "repo", "rep", "domain", "source_repo", "source_repository")
        )
        if re.search(
            r"terminal[-_ ]?bench|human[-_ ]?eval|(?:^|[^a-z0-9])(?:tb21|mbpp|ifeval)(?:$|[^a-z0-9])", provenance, re.I
        ):
            flags.add("benchmark_source")
        if "source_license" in mapping:
            license_name = str(mapping["source_license"] or "").strip().lower()
            if (
                license_name in {"", "none", "null"}
                or re.match(r"^(unknown|other)(?:$|[^a-z])", license_name)
                or re.search(r"(?:^|[^a-z])nc(?:$|[^a-z])|non[- ]?commercial", license_name)
            ):
                flags.add("source_license_review")
    return sorted(flags)


def ability_domain(raw, source_id):
    """Map explicit source domains only; do not classify task text by keywords."""
    if "fineenvs" in str(source_id).lower() or "huggingenvs/data-agent" in str(source_id).lower():
        return "data"
    value = raw.get("domain") or _metadata(raw).get("domain")
    if not isinstance(value, str):
        return "unknown"
    domain = value.strip().lower().replace("-", "_").replace(" ", "_")
    if domain in {"code", "coding", "security", "harness"} or domain.startswith("terminal"):
        return "code"
    if domain in {"math", "reasoning", "science_logic_data", "math_formal"}:
        return "reasoning"
    if domain in {"instruction", "strict_instruction", "general"}:
        return "general"
    if domain in {"office", "data", "translation", "writing"}:
        return domain
    return "unknown"
