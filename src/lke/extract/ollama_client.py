"""Free local model through Ollama (https://ollama.com): no API key, nothing leaves the computer."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any

from lke.config import LlmConfig
from lke.extract.llm_client import LLMBadOutput, LLMSetupError, LLMTruncated, UsageTracker


class OllamaLLM:
    """Same interface as AnthropicLLM. Output is forced to match the JSON schema."""

    def __init__(self, cfg: LlmConfig):
        self.cfg = cfg
        self.url = cfg.ollama_url.rstrip("/")
        self.usage = UsageTracker()
        self._slots = threading.Semaphore(max(1, cfg.max_concurrent_requests))

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self.url + path, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.cfg.ollama_timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code == 404:
                raise LLMSetupError(
                    f"Ollama model '{self.cfg.ollama_model}' is not installed. "
                    f"Run: ollama pull {self.cfg.ollama_model}") from None
            raise LLMBadOutput(f"Ollama error {e.code}: {body[:300]}") from None
        except (urllib.error.URLError, ConnectionError) as e:
            raise LLMSetupError(
                f"Cannot reach Ollama at {self.url} ({e}). Is the Ollama app running?") from None

    def check(self) -> None:
        """Fail early with a clear message if Ollama or the model is missing."""
        self._post("/api/show", {"model": self.cfg.ollama_model})

    def complete_json(self, *, model: str, system: str, user: str, schema: dict[str, Any],
                      effort: str | None = None, max_tokens: int | None = None
                      ) -> dict[str, Any]:
        local_model = self.cfg.ollama_model            # one local model does every task
        payload = {
            "model": local_model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "format": schema,
            "stream": False,
            "options": {
                "temperature": 0,
                "num_ctx": self.cfg.ollama_context,
                # output must fit in the context window together with the input
                "num_predict": min(max_tokens or self.cfg.max_output_tokens,
                                   self.cfg.ollama_context // 2),
            },
        }
        with self._slots:
            data = self._post("/api/chat", payload)
        self.usage.add(local_model, _Usage(data.get("prompt_eval_count", 0),
                                           data.get("eval_count", 0)))
        if data.get("done_reason") == "length":
            raise LLMTruncated("local model ran out of output space; lower sectioning sizes "
                               "or raise ollama_context in config.yaml")
        text = (data.get("message") or {}).get("content", "")
        try:
            result = json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMBadOutput(f"invalid JSON from local model: {e}") from e
        if not isinstance(result, dict):
            raise LLMBadOutput("expected a JSON object")
        return result


class _Usage:
    def __init__(self, input_tokens: int, output_tokens: int):
        self.input_tokens, self.output_tokens = input_tokens, output_tokens
