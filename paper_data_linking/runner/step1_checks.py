"""Checks on a step-1 (paper analysis) answer before it is accepted.

Gemma 4 occasionally produces a degenerate answer: it opens with "---" and repeats
separator lines until the length cap. With "---" as a stop sequence that shows up as
an empty answer instead. Both, and a few related shapes, are caught here so the
runner can ask again; a fresh sample at temperature 1.0 is almost always fine.
"""

from typing import Optional

FORM_HEADER = "Scientific Observation Instrumentation Form"
LOOP_RUN_LENGTH = 20


def looping(text: str, n: int = LOOP_RUN_LENGTH) -> bool:
    """The same non-blank line repeated ``n`` or more times in a row."""
    run, prev = 0, None
    for line in (l.strip() for l in text.splitlines()):
        if not line:
            continue
        run = run + 1 if line == prev else 1
        prev = line
        if run >= n:
            return True
    return False


def step1_problem(content: Optional[str], finish_reason: Optional[str]) -> Optional[str]:
    """Why this answer should be retried, or None if it is acceptable."""
    text = (content or "").strip()
    if not text:
        return "empty"
    if finish_reason != "stop":
        return f"finish_reason={finish_reason}"
    if looping(text):
        return "looping"
    if FORM_HEADER not in text and not text.startswith("No instruments"):
        return "no_form_header"
    return None
