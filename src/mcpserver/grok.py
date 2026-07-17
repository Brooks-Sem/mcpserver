from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)

from .config import VALID_EFFORTS, GrokConfig
from .models import ConversationResult
from .sessions import SessionStore

_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class GrokProtocolError(RuntimeError):
    pass


def _is_retryable(error: BaseException) -> bool:
    if isinstance(error, httpx.ConnectError | httpx.RemoteProtocolError):
        return True
    return isinstance(error, httpx.HTTPStatusError) and (
        error.response.status_code in _RETRYABLE_STATUS_CODES
    )


def _extract_message(payload: dict[str, Any]) -> tuple[str, str | None]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise GrokProtocolError("Grok response did not contain choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise GrokProtocolError("Grok response did not contain a message")
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") in {"text", "output_text"}
        )
    if not isinstance(content, str) or not content:
        raise GrokProtocolError("Grok response message did not contain text content")
    reasoning = message.get("reasoning_content") or message.get("reasoning")
    return content, reasoning if isinstance(reasoning, str) else None


def _extract_responses_message(
    payload: dict[str, Any],
) -> tuple[str, str | None, list[dict[str, str]]]:
    output = payload.get("output")
    if not isinstance(output, list):
        raise GrokProtocolError("Grok response did not contain an output list")
    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    sources: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "reasoning":
            summary = item.get("summary")
            if isinstance(summary, list):
                reasoning_parts.extend(
                    part["text"]
                    for part in summary
                    if isinstance(part, dict) and isinstance(part.get("text"), str)
                )
        if item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") not in {"output_text", "text"}:
                continue
            text = part.get("text")
            if isinstance(text, str) and text:
                text_parts.append(text)
            annotations = part.get("annotations")
            if not isinstance(annotations, list):
                continue
            for annotation in annotations:
                if not isinstance(annotation, dict):
                    continue
                url = annotation.get("url")
                if not isinstance(url, str) or not url or url in seen_urls:
                    continue
                title = annotation.get("title")
                sources.append({"url": url, "title": title if isinstance(title, str) else ""})
                seen_urls.add(url)
    citations = payload.get("citations")
    if isinstance(citations, list):
        for citation in citations:
            url = citation if isinstance(citation, str) else None
            title = ""
            if isinstance(citation, dict):
                url = citation.get("url")
                raw_title = citation.get("title")
                title = raw_title if isinstance(raw_title, str) else ""
            if isinstance(url, str) and url and url not in seen_urls:
                sources.append({"url": url, "title": title})
                seen_urls.add(url)
    if not text_parts:
        raise GrokProtocolError("Grok response output did not contain text")
    return "".join(text_parts), "\n".join(reasoning_parts) or None, sources


@dataclass(frozen=True)
class GrokResponse:
    content: str
    reasoning: str | None
    model: str
    usage: dict[str, Any]
    sources: list[dict[str, str]]
    server_side_tool_usage: dict[str, Any]


class GrokClient:
    def __init__(
        self,
        config: GrokConfig,
        *,
        session_store: SessionStore | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.session_store = session_store or SessionStore()
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def _chat_payload(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        reasoning_effort: str,
    ) -> dict[str, Any]:
        if reasoning_effort not in VALID_EFFORTS:
            raise ValueError(f"Unsupported reasoning effort: {reasoning_effort}")
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if self.config.reasoning_field:
            payload[self.config.reasoning_field] = reasoning_effort
        return payload

    async def list_models(self) -> list[str]:
        payload = await self._request_json("GET", "/models")
        data = payload.get("data")
        if not isinstance(data, list):
            raise GrokProtocolError("Grok /models response did not contain a data list")
        models = [
            item["id"]
            for item in data
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]
        ]
        if not models:
            raise GrokProtocolError("Grok /models response did not contain model IDs")
        return models

    async def start(
        self,
        prompt: str,
        *,
        model: str | None = None,
        reasoning_effort: str | None = None,
        system_prompt: str | None = None,
        web_search: bool = True,
    ) -> ConversationResult:
        effective_model = model or self.config.model
        effective_effort = reasoning_effort or self.config.reasoning_effort
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        response = await self._chat(
            messages,
            model=effective_model,
            reasoning_effort=effective_effort,
            web_search=web_search,
        )
        messages.append({"role": "assistant", "content": response.content})
        session_id = self.session_store.create("grok", response.model, messages)
        return ConversationResult(
            result=response.content,
            session_id=session_id,
            model=response.model,
            metadata={
                "reasoningEffort": effective_effort,
                "reasoning": response.reasoning,
                "usage": response.usage,
                "webSearch": web_search,
                "sources": response.sources,
                "serverSideToolUsage": response.server_side_tool_usage,
                "sessionPersistence": "local-sqlite",
            },
        )

    async def reply(
        self,
        session_id: str,
        prompt: str,
        *,
        model: str | None = None,
        reasoning_effort: str | None = None,
        web_search: bool = True,
    ) -> ConversationResult:
        stored_model, messages = self.session_store.load(session_id, "grok")
        effective_model = model or stored_model
        effective_effort = reasoning_effort or self.config.reasoning_effort
        messages.append({"role": "user", "content": prompt})
        response = await self._chat(
            messages,
            model=effective_model,
            reasoning_effort=effective_effort,
            web_search=web_search,
        )
        messages.append({"role": "assistant", "content": response.content})
        self.session_store.save(session_id, "grok", response.model, messages)
        return ConversationResult(
            result=response.content,
            session_id=session_id,
            model=response.model,
            metadata={
                "reasoningEffort": effective_effort,
                "reasoning": response.reasoning,
                "usage": response.usage,
                "webSearch": web_search,
                "sources": response.sources,
                "serverSideToolUsage": response.server_side_tool_usage,
                "sessionPersistence": "local-sqlite",
            },
        )

    async def _chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        reasoning_effort: str,
        web_search: bool,
    ) -> GrokResponse:
        if web_search:
            return await self._responses(
                messages,
                model=model,
                reasoning_effort=reasoning_effort,
            )
        payload = self._chat_payload(
            messages,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        data = await self._request_json("POST", "/chat/completions", json_body=payload)
        content, reasoning = _extract_message(data)
        response_model = data.get("model") if isinstance(data.get("model"), str) else model
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return GrokResponse(content, reasoning, response_model, usage, [], {})

    async def _responses(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        reasoning_effort: str,
    ) -> GrokResponse:
        if reasoning_effort not in VALID_EFFORTS:
            raise ValueError(f"Unsupported reasoning effort: {reasoning_effort}")
        payload: dict[str, Any] = {
            "model": model,
            "input": messages,
            "store": False,
            "tools": [{"type": "web_search"}],
        }
        if self.config.reasoning_field:
            payload["reasoning"] = {"effort": reasoning_effort}
        data = await self._request_json("POST", "/responses", json_body=payload)
        content, reasoning, sources = _extract_responses_message(data)
        response_model = data.get("model") if isinstance(data.get("model"), str) else model
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        tool_usage = (
            data.get("server_side_tool_usage")
            if isinstance(data.get("server_side_tool_usage"), dict)
            else {}
        )
        return GrokResponse(content, reasoning, response_model, usage, sources, tool_usage)

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        timeout = httpx.Timeout(self.config.timeout_seconds, connect=10.0)
        async with httpx.AsyncClient(
            base_url=self.config.api_url,
            headers=self._headers(),
            timeout=timeout,
            follow_redirects=True,
            transport=self.transport,
        ) as client:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.config.max_retries),
                wait=wait_random_exponential(multiplier=1, max=10),
                retry=retry_if_exception(_is_retryable),
                reraise=True,
            ):
                with attempt:
                    response = await client.request(method, path, json=json_body)
                    response.raise_for_status()
                    try:
                        payload = response.json()
                    except ValueError as error:
                        raise GrokProtocolError(
                            "Grok endpoint returned non-JSON content"
                        ) from error
                    if not isinstance(payload, dict):
                        raise GrokProtocolError("Grok endpoint returned a non-object JSON payload")
                    return payload
        raise AssertionError("unreachable")
