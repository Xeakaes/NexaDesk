from dataclasses import dataclass


@dataclass
class AgentConfig:
    max_tool_calls: int = 10
    tool_timeout_s: float = 30.0
    model_timeout_s: float = 60.0
    # Most recent image-bearing message kept with images attached.
    # Older base64 blobs are dropped from the session so they cannot
    # accumulate in memory or get re-sent to the model on every call.
    max_history_images: int = 1
    # Optional user-defined system prompt, prepended to every model call.
    persona: str = ""
