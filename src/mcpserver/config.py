from __future__ import annotations

import os
from dataclasses import dataclass

VALID_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})


@dataclass(frozen=True)
class GrokConfig:
    api_url: str
    api_key: str
    model: str
    reasoning_effort: str
    reasoning_field: str | None
    timeout_seconds: float
    max_retries: int

    @classmethod
    def from_env(cls) -> GrokConfig:
        api_url = os.getenv("GROK_API_URL", "").strip().rstrip("/")
        api_key = os.getenv("GROK_API_KEY", "").strip()
        if not api_url:
            raise ValueError("GROK_API_URL is required")
        if not api_key:
            raise ValueError("GROK_API_KEY is required")
        effort = os.getenv("GROK_REASONING_EFFORT", "high").strip().lower()
        if effort not in VALID_EFFORTS:
            raise ValueError(f"Unsupported GROK_REASONING_EFFORT: {effort}")
        field = os.getenv("GROK_REASONING_FIELD", "reasoning_effort").strip()
        return cls(
            api_url=api_url,
            api_key=api_key,
            model=os.getenv("GROK_MODEL", "grok-4").strip(),
            reasoning_effort=effort,
            reasoning_field=field or None,
            timeout_seconds=float(os.getenv("GROK_TIMEOUT_SECONDS", "180")),
            max_retries=int(os.getenv("GROK_MAX_RETRIES", "3")),
        )

    def masked(self) -> dict[str, object]:
        return {
            "apiUrl": self.api_url,
            "apiKeyConfigured": bool(self.api_key),
            "model": self.model,
            "reasoningEffort": self.reasoning_effort,
            "reasoningField": self.reasoning_field,
            "timeoutSeconds": self.timeout_seconds,
            "maxRetries": self.max_retries,
        }
