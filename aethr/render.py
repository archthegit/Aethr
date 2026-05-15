"""Shared text rendering helpers for terminal and local UI output."""

from __future__ import annotations

import re
import textwrap


def clean_display_text(text: str) -> str:
    """Remove common markdown markers before rendering output."""

    cleaned_lines: list[str] = []
    in_code_block = False

    for raw_line in textwrap.dedent(text).strip().splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue

        if in_code_block:
            cleaned_lines.append(line)
            continue

        heading = re.match(r"^\s{0,3}#{1,6}\s+(.*)$", line)
        if heading is not None:
            cleaned_lines.append(heading.group(1).strip())
            continue

        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", line)
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"\1", line)
        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned
