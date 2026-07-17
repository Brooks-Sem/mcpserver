from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


class ConversationResponse(BaseModel):
    result: str
    sessionId: str
    model: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GrokConfigResponse(BaseModel):
    apiUrl: str
    apiKeyConfigured: bool
    model: str
    reasoningEffort: str
    reasoningField: str | None
    timeoutSeconds: float
    maxRetries: int


class GrokModelsResponse(BaseModel):
    models: list[str]
    config: GrokConfigResponse


class DeleteSessionResponse(BaseModel):
    sessionId: str
    deleted: bool


@dataclass(frozen=True)
class ConversationResult:
    result: str
    session_id: str
    model: str | None = None
    metadata: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "sessionId": self.session_id,
            "model": self.model,
            "metadata": self.metadata or {},
        }

    def as_response(self) -> ConversationResponse:
        return ConversationResponse(**self.as_dict())
