"""Independent T2 business oracle. Does not execute student tools or judge DSH lifecycle."""

import re

FIELDS = ("timestamp", "service", "severity", "message")
REDACTION = "[REDACTED_EMAIL]"
LOCAL = r"[A-Za-z0-9_%+-]+(?:\.[A-Za-z0-9_%+-]+)*"
LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
EMAIL_PATTERN = re.compile(
    r"(?<![\w.%+@-])" + LOCAL + "@" + LABEL + r"(?:\." + LABEL + r")*\.[A-Za-z]{2,}"
    r"(?![\w@-]|\.[A-Za-z0-9])"
)


def evaluate(records, *, severity=None, service=None):
    """Filter valid records by exact AND conditions, project fields and redact message emails.

    None means no filter; missing/non-string record fields are skipped. Empty
    strings are valid. Input order and duplicates are preserved; input is unchanged.
    The email regex defines this task's grammar, not general RFC validation.
    """
    if not isinstance(records, list):
        raise ValueError("records must be an array")
    if any(value is not None and not isinstance(value, str) for value in (severity, service)):
        raise ValueError("severity and service must be strings or null")
    output = []
    for record in records:
        if not isinstance(record, dict) or any(not isinstance(record.get(field), str) for field in FIELDS):
            continue
        if severity is not None and record["severity"] != severity:
            continue
        if service is not None and record["service"] != service:
            continue
        projected = {field: record[field] for field in FIELDS}
        projected["message"] = EMAIL_PATTERN.sub(REDACTION, projected["message"])
        output.append(projected)
    return output
