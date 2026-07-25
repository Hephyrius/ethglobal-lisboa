"""Finding the JSON object inside whatever a small open model actually said.

This is layer 1 of output validation. It is separated from schema validation
because the failures are completely different in kind: here we are recovering
from *presentation* mistakes, not from a model that misunderstood the task, and
the retry hint we want to give back is correspondingly different.

The failure modes below are the ones a 14B instruct model actually produces, in
rough order of frequency:

    ```json { ... } ```                 fenced, sometimes with the language tag
    Here is my decision: { ... }        prose preamble
    { ... }  Let me explain why...      prose postscript
    <think> ... </think> { ... }        reasoning-model preamble
    { ..., }                            trailing comma before } or ]
    { ... } { ... }                     a draft followed by the real answer

Nothing here repairs *meaning* — a recovered object still has to pass the schema
and the mandate. This only stops the harness from rejecting a correct decision
because the model wrapped it in a code fence.
"""

from __future__ import annotations

import json
import re
from typing import Any

__all__ = ["extract_json_object", "ExtractionError"]

#: Reasoning models emit these before the answer; the content is not JSON and
#: can itself contain braces, so it is removed before scanning.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
#: A trailing comma before a closing brace/bracket. Legal in JS, not in JSON.
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


class ExtractionError(ValueError):
    """No JSON object could be recovered from the model's response."""


def _balanced_objects(text: str) -> list[str]:
    """Every top-level `{...}` span, string- and escape-aware.

    A naive `text[text.find("{"):text.rfind("}") + 1]` swallows two objects into
    one unparseable blob, and a regex cannot balance braces at all. Scanning
    also has to ignore braces inside string literals — `reasoning` fields quote
    market data and occasionally contain them.
    """
    spans: list[str] = []
    depth = 0
    start: int | None = None
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                spans.append(text[start : index + 1])
                start = None

    return spans


def _try_load(candidate: str) -> Any | None:
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    # One conservative repair pass. Trailing commas are the single most common
    # syntax error from models trained on JavaScript, and fixing them changes no
    # semantics. Nothing else is repaired — silently "fixing" a malformed
    # decision is precisely the risk this layer exists to avoid.
    try:
        return json.loads(_TRAILING_COMMA.sub(r"\1", candidate))
    except json.JSONDecodeError:
        return None


def extract_json_object(raw: str, *, expect_key: str | None = "action") -> dict[str, Any]:
    """Recover the decision object from a raw model response.

    When several objects are present — a model that drafted, reconsidered, and
    answered — the first one carrying `expect_key` wins. That is more reliable
    than "first" or "last" alone: a preamble object rarely has the answer's
    shape, and picking by shape survives both orderings.

    Raises `ExtractionError` with a message written to be fed straight back to
    the model as a retry instruction.
    """
    if not raw or not raw.strip():
        raise ExtractionError("your response was empty; return a single JSON object")

    text = _THINK_BLOCK.sub(" ", raw)
    candidates = _balanced_objects(text)

    if not candidates:
        raise ExtractionError(
            "no JSON object found in your response; return only a single JSON "
            "object, with no explanation around it"
        )

    parsed = [obj for obj in (_try_load(c) for c in candidates) if isinstance(obj, dict)]

    if not parsed:
        raise ExtractionError(
            "the JSON in your response could not be parsed; return a single "
            "syntactically valid JSON object and nothing else"
        )

    if expect_key:
        for obj in parsed:
            if expect_key in obj:
                return obj
        raise ExtractionError(
            f"your JSON object has no {expect_key!r} field; return a single JSON "
            f"object with {expect_key!r} set"
        )

    return parsed[0]
