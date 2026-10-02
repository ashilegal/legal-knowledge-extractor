"""Claude API wrapper: retries, rate limit, cost tracking."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic

from lke.config import LlmConfig

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    """The model call did not produce usable output."""


class LLMSetupError(Exception):
    """The model cannot be used at all (not running, not installed, bad key): stop the run."""


class LLMRefusal(LLMError):
    """The model declined the request (stop_reason == 'refusal')."""


class LLMTruncated(LLMError):
    """Output hit max_tokens before the JSON was complete."""


class LLMBadOutput(LLMError):
    """Output was not valid JSON."""


@dataclass
class ModelUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class UsageTracker:
    """Token counts per model, safe to update from several threads."""

    by_model: dict[str, ModelUsage] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, model: str, usage: Any) -> None:
        with self._lock:
            m = self.by_model.setdefault(model, ModelUsage())
            m.calls += 1
            m.input_tokens += getattr(usage, "input_tokens", 0) or 0
            m.output_tokens += getattr(usage, "output_tokens", 0) or 0
            m.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
            m.cache_write_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0

    def cost(self, prices: dict[str, tuple[float, float]]) -> float:
        """Approximate USD: cache reads at 10%, cache writes at 125% of the input price."""
        total = 0.0
        for model, u in self.by_model.items():
            inp, out = prices.get(model, (0.0, 0.0))
            total += (u.input_tokens * inp + u.cache_read_tokens * inp * 0.1
                      + u.cache_write_tokens * inp * 1.25 + u.output_tokens * out) / 1_000_000
        return round(total, 4)

    def to_dict(self) -> dict[str, dict[str, int]]:
        return {m: vars(u).copy() for m, u in self.by_model.items()}


class JsonLLM(Protocol):
    """Anything that can answer a prompt with JSON matching a schema."""

    usage: UsageTracker

    def complete_json(
        self, *, model: str, system: str, user: str, schema: dict[str, Any],
        effort: str | None = None, max_tokens: int | None = None,
    ) -> dict[str, Any]: ...


def supports_effort(model: str) -> bool:
    return not model.startswith("claude-haiku")


def supports_fallback(model: str) -> bool:
    return model.startswith(("claude-opus-5", "claude-sonnet-5-5", "claude-fable-5"))


class AnthropicLLM:
    """Claude via the official SDK, with structured JSON output.

    The SDK already retries network errors, 408/409/429 and 5xx with backoff
    (max_retries). This class limits parallel calls, records token usage and
    turns refusals / truncation / bad JSON into clear exceptions.
    """

    def __init__(self, cfg: LlmConfig, client: anthropic.Anthropic | None = None):
        self.cfg = cfg
        self.client = client or anthropic.Anthropic(max_retries=cfg.max_retries, timeout=600.0)
        self.usage = UsageTracker()
        self._slots = threading.Semaphore(cfg.max_concurrent_requests)
        self._fallback_ok = cfg.refusal_fallback

    def complete_json(
        self, *, model: str, system: str, user: str, schema: dict[str, Any],
        effort: str | None = None, max_tokens: int | None = None,
    ) -> dict[str, Any]:
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
        if effort and supports_effort(model):
            output_config["effort"] = effort
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens or self.cfg.max_output_tokens,
            # the instructions are identical for every section -> cache them
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
            "output_config": output_config,
        }
        with self._slots:
            response = self._send(params)
        self.usage.add(model, response.usage)

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise LLMRefusal(f"model declined the request (category: {category})")
        if response.stop_reason == "max_tokens":
            raise LLMTruncated(f"output exceeded max_tokens={params['max_tokens']}")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMBadOutput(f"invalid JSON from model: {e}") from e
        if not isinstance(data, dict):
            raise LLMBadOutput("expected a JSON object")
        return data

    def _send(self, params: dict[str, Any]) -> Any:
        if self._fallback_ok and supports_fallback(params["model"]):
            try:
                return self.client.beta.messages.create(
                    **params, betas=[FALLBACK_BETA], fallbacks="default")
            except anthropic.BadRequestError as e:
                # e.g. the account or platform doesn't offer fallbacks: carry on without
                log.warning("refusal fallback unavailable (%s); continuing without it", e)
                self._fallback_ok = False
        return self.client.messages.create(**params)


def make_llm(cfg: LlmConfig) -> JsonLLM:
    """'anthropic' (paid API) or 'ollama' (free, runs on this computer)."""
    if cfg.provider == "ollama":
        from lke.extract.ollama_client import OllamaLLM
        return OllamaLLM(cfg)
    if cfg.provider == "anthropic":
        return AnthropicLLM(cfg)
    raise ValueError(f"unknown llm.provider '{cfg.provider}' (use 'ollama' or 'anthropic')")
