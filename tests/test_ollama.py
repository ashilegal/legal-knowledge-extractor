import json

import pytest

from lke.config import LlmConfig
from lke.extract import LLMSetupError, LLMTruncated, make_llm
from lke.extract.ollama_client import OllamaLLM


def test_provider_switch():
    assert isinstance(make_llm(LlmConfig(provider="ollama")), OllamaLLM)
    with pytest.raises(ValueError):
        make_llm(LlmConfig(provider="other"))


def test_request_uses_schema_and_local_model(monkeypatch):
    llm = OllamaLLM(LlmConfig(ollama_model="qwen2.5:7b"))
    sent = {}

    def fake_post(path, payload):
        sent.update(payload, path=path)
        return {"message": {"content": json.dumps({"items": []})}, "done_reason": "stop",
                "prompt_eval_count": 1200, "eval_count": 80}
    monkeypatch.setattr(llm, "_post", fake_post)
    out = llm.complete_json(model="claude-opus-5-5", system="rules", user="text",
                            schema={"type": "object"})
    assert out == {"items": []}
    assert sent["path"] == "/api/chat" and sent["model"] == "qwen2.5:7b"
    assert sent["format"] == {"type": "object"} and sent["options"]["temperature"] == 0
    assert llm.usage.by_model["qwen2.5:7b"].input_tokens == 1200


def test_truncated_output(monkeypatch):
    llm = OllamaLLM(LlmConfig())
    monkeypatch.setattr(llm, "_post", lambda p, d: {"message": {"content": "{"},
                                                    "done_reason": "length"})
    with pytest.raises(LLMTruncated):
        llm.complete_json(model="x", system="s", user="u", schema={})


def test_not_running_gives_clear_message():
    llm = OllamaLLM(LlmConfig(ollama_url="http://127.0.0.1:9", ollama_timeout=2))
    with pytest.raises(LLMSetupError, match="Is the Ollama app running"):
        llm.check()
