"""Small DeepSeek Chat Completions adapter. Never persist provider raw responses."""

import json
import re
from typing import Protocol

import httpx

from app.agent_store import redact
from app.errors import BusinessError


class ChatModel(Protocol):
    provider: str
    model_id: str

    def complete(self, messages: list[dict], tools: list[dict], timeout: float) -> dict: ...


class DeepSeekModel:
    provider = "deepseek"
    final_repair = True

    def __init__(self, settings, *, transport=None):
        if not settings.deepseek_api_key or not settings.deepseek_api_key.get_secret_value():
            raise BusinessError("MODEL_CREDENTIALS_MISSING", 503)
        self.model_id = settings.deepseek_model
        self.key = settings.deepseek_api_key.get_secret_value()
        self.transport = transport

    def complete(self, messages, tools, timeout):
        payload = {
            "model": self.model_id,
            "messages": messages,
            "tools": tools,
            "thinking": {"type": "disabled"},
            "temperature": 0,
            "max_tokens": 1536,
        }
        # JSON mode with auto tools can emit textual tool markup instead of native calls.
        # Use native tool calling for selection, and JSON mode for a bounded final repair.
        if not tools:
            payload["response_format"] = {"type": "json_object"}
        try:
            with httpx.Client(transport=self.transport, timeout=timeout, trust_env=False) as client:
                # A whole-response wall deadline is also enforced when persisting the result.
                response = client.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={"Authorization": "Bearer " + self.key},
                    json=payload,
                )
                if response.status_code != 200:
                    code = {
                        401: "MODEL_AUTH_FAILED",
                        402: "MODEL_BALANCE_INSUFFICIENT",
                        429: "MODEL_RATE_LIMITED",
                    }.get(response.status_code, "MODEL_UNAVAILABLE")
                    raise BusinessError(code, 503, retryable=response.status_code >= 429)
                raw = response.json()
        except httpx.TimeoutException:
            raise BusinessError("MODEL_TIMEOUT", 503, retryable=True) from None
        except (httpx.HTTPError, ValueError):
            raise BusinessError("MODEL_UNAVAILABLE", 503, retryable=True) from None
        try:
            choice = raw["choices"][0]
            if choice["finish_reason"] not in {"stop", "tool_calls"}:
                raise ValueError("Incomplete output")
            message = choice["message"]
            calls = message.get("tool_calls") or []
            if len(calls) > 4:
                raise ValueError("Too many calls")
            normalized, ids = [], set()
            for call in calls:
                call_id = call["id"]
                name = call["function"]["name"]
                if (
                    not isinstance(call_id, str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", call_id)
                    or call_id in ids
                    or not isinstance(name, str)
                    or len(name) > 64
                ):
                    raise ValueError("Invalid call")
                ids.add(call_id)
                try:
                    arguments = json.loads(call["function"]["arguments"])
                except (ValueError, TypeError):
                    arguments = None
                normalized.append({"id": call_id, "name": name, "arguments": arguments})
            usage = raw.get("usage", {})
            usage = {
                name: value
                for name, value in usage.items()
                if name
                in {
                    "prompt_tokens",
                    "completion_tokens",
                    "total_tokens",
                    "prompt_cache_hit_tokens",
                    "prompt_cache_miss_tokens",
                }
                and type(value) is int
                and value >= 0
            }
            actual_model = raw.get("model")
            if not isinstance(actual_model, str) or len(actual_model) > 128:
                raise ValueError("Missing model")
            return {
                "calls": normalized,
                "content": redact(message.get("content") or ""),
                "usage": usage,
                "model": actual_model,
            }
        except (KeyError, IndexError, TypeError, ValueError):
            raise BusinessError("MODEL_RESPONSE_INVALID", 503) from None
