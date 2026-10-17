import copy
from typing import Any

from litellm import Message

CACHED_TAIL_LENGTH = 3


def _with_cache_control(content: Any) -> Any:
    if isinstance(content, str):
        return [
            {"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}
        ]
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and "type" in item:
                item["cache_control"] = {"type": "ephemeral"}
    return content


def add_anthropic_caching(
    messages: list[dict[str, Any] | Message], model_name: str
) -> list[dict[str, Any] | Message]:
    """Mark the most recent messages as ephemeral-cacheable for Anthropic models."""
    if "anthropic" not in model_name.lower() and "claude" not in model_name.lower():
        return messages

    cached_messages = copy.deepcopy(messages)
    for msg in cached_messages[-CACHED_TAIL_LENGTH:]:
        if isinstance(msg, dict):
            msg["content"] = _with_cache_control(msg.get("content"))
        elif hasattr(msg, "content"):
            msg.content = _with_cache_control(msg.content)  # type: ignore[assignment]

    return cached_messages
