"""OpenRouter client with a fallback chain across free models.

Never raises on model failure — walks the chain and only raises LLMUnavailable
when every model has been exhausted, so callers can degrade gracefully.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class LLMUnavailable(RuntimeError):
    """Raised when the whole fallback chain failed or no API key is configured."""


@dataclass
class LLMResult:
    text: str
    model: str


class LLMClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        models: Optional[List[str]] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.openrouter_api_key
        self.models = models or settings.model_chain
        self.base_url = (base_url or settings.openrouter_base_url).rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # Optional OpenRouter attribution headers.
            "HTTP-Referer": "https://github.com/job-matching-agent",
            "X-Title": settings.app_name,
        }

    async def complete(
        self,
        prompt: str,
        system: str = "You are a helpful assistant.",
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResult:
        """Try each model in the chain until one succeeds."""
        if not self.enabled:
            raise LLMUnavailable(
                "OPENROUTER_API_KEY is not configured — LLM features disabled."
            )

        payload_messages = messages or [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

        errors: List[str] = []
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            for model in self.models:
                body: Dict[str, Any] = {
                    "model": model,
                    "messages": payload_messages,
                    "max_tokens": max_tokens or settings.llm_max_tokens,
                    "temperature": (
                        temperature
                        if temperature is not None
                        else settings.llm_temperature
                    ),
                }
                if tools:
                    body["tools"] = tools
                try:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=self._headers(),
                        json=body,
                    )
                    if resp.status_code in RETRYABLE_STATUS:
                        errors.append(f"{model}: HTTP {resp.status_code}")
                        logger.warning(
                            "Model %s returned %s, falling back", model, resp.status_code
                        )
                        await asyncio.sleep(0.6)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    choice = (data.get("choices") or [{}])[0]
                    text = (choice.get("message") or {}).get("content") or ""
                    if not text.strip():
                        errors.append(f"{model}: empty response")
                        continue
                    return LLMResult(text=text.strip(), model=model)
                except httpx.HTTPStatusError as exc:
                    errors.append(f"{model}: HTTP {exc.response.status_code}")
                except (httpx.TimeoutException, httpx.HTTPError) as exc:
                    errors.append(f"{model}: {type(exc).__name__}")
                except Exception as exc:  # noqa: BLE001 - defensive
                    errors.append(f"{model}: {exc}")

        raise LLMUnavailable("All models failed -> " + "; ".join(errors))

    async def complete_message(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> tuple[Dict[str, Any], str]:
        """Like complete() but returns the raw assistant message (incl. tool_calls)."""
        if not self.enabled:
            raise LLMUnavailable("OPENROUTER_API_KEY is not configured.")

        errors: List[str] = []
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            for model in self.models:
                body: Dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens or settings.llm_max_tokens,
                    "temperature": (
                        temperature if temperature is not None else settings.llm_temperature
                    ),
                }
                if tools:
                    body["tools"] = tools
                    body["tool_choice"] = "auto"
                try:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=self._headers(),
                        json=body,
                    )
                    if resp.status_code in RETRYABLE_STATUS:
                        errors.append(f"{model}: HTTP {resp.status_code}")
                        await asyncio.sleep(0.6)
                        continue
                    if resp.status_code == 404 and tools:
                        # Model doesn't support tool calling — try the next one.
                        errors.append(f"{model}: no tool support")
                        continue
                    resp.raise_for_status()
                    message = (resp.json().get("choices") or [{}])[0].get("message") or {}
                    if message.get("content") or message.get("tool_calls"):
                        return message, model
                    errors.append(f"{model}: empty message")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{model}: {type(exc).__name__}")

        raise LLMUnavailable("All models failed -> " + "; ".join(errors))

    async def complete_json(
        self,
        prompt: str,
        system: str = "You reply with valid JSON only.",
        max_tokens: Optional[int] = None,
    ) -> Any:
        """Ask for JSON and parse defensively (models often wrap in fences/prose)."""
        result = await self.complete(
            prompt,
            system=system + " Respond with raw JSON only, no markdown fences, no prose.",
            max_tokens=max_tokens,
            temperature=0.1,
        )
        return extract_json(result.text)


def extract_json(text: str) -> Any:
    """Best-effort JSON extraction from an LLM response."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost {...} or [...] block.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"Could not parse JSON from LLM response: {text[:200]}")


llm_client = LLMClient()
