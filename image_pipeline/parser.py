from __future__ import annotations

import re


def extract_regex_value(text: str, pattern: str, field_name: str) -> dict[str, str]:
    match = re.search(pattern, text)
    value = match.group(1) if match and match.groups() else (match.group(0) if match else "")
    return {field_name: value}
