"""
Helpers for padding prompts to emulate different LLM latency levels.

Padding is controlled via environment variables so that each evaluation run can
configure a different effective prompt size without changing code:

    PROMPT_PADDING_CHARS: integer, approximate number of characters of padding
                          to append to the first user message (default: 0).
    PROMPT_PADDING_TEXT:  optional custom padding text to repeat. If not set,
                          a default neutral filler text is used.

Example:

    PROMPT_PADDING_CHARS=5000 uv run python mcp_completion_script.py ...
"""

from __future__ import annotations

import os
from typing import List

from .schema import Message, UserMessage


def _get_padding_text() -> str:
    base_text = os.getenv(
        "PROMPT_PADDING_TEXT",
        (
            "The following block is padding added to emulate higher latency for "
            "large prompts. It does not contain any information relevant to the "
            "task and should be ignored when reasoning.\n"
        ),
    )
    return base_text


def _build_padding(target_chars: int) -> str:
    if target_chars <= 0:
        return ""

    unit = _get_padding_text()
    if not unit:
        return ""

    repeats = max(1, target_chars // len(unit))
    padding = unit * repeats
    # Trim to at most target_chars + len(unit) to avoid excessive overrun
    return padding[: target_chars + len(unit)]


def apply_prompt_padding(messages: List[Message]) -> List[Message]:
    """
    Return a copy of `messages` where the first user message's content is padded
    with neutral filler text, if PROMPT_PADDING_CHARS > 0.
    """
    try:
        padding_chars = int(os.getenv("PROMPT_PADDING_CHARS", "0"))
    except ValueError:
        padding_chars = 0

    if padding_chars <= 0:
        return list(messages)

    padding = _build_padding(padding_chars)
    if not padding:
        return list(messages)

    padded_messages: List[Message] = []
    user_padded = False

    for msg in messages:
        if not user_padded and isinstance(msg, UserMessage):
            new_content = msg.content + "\n\n" + padding
            padded_messages.append(UserMessage(role=msg.role, content=new_content))
            user_padded = True
        else:
            padded_messages.append(msg)

    return padded_messages

