import io
import importlib.util
import json
from pathlib import Path
from urllib import error

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "translate_md.py"
MODULE_SPEC = importlib.util.spec_from_file_location("translate_md", MODULE_PATH)
translate_md = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
MODULE_SPEC.loader.exec_module(translate_md)


def test_build_request_payload_uses_deepseek_chat_defaults():
    payload = translate_md.build_request_payload(
        "Translate this block.",
        "deepseek-chat",
        "en",
        "zh",
    )

    assert payload == {
        "model": "deepseek-chat",
        "stream": False,
        "max_tokens": 8192,
        "messages": [
            {
                "role": "system",
                "content": "You are a professional academic translator. Follow the user's Markdown preservation requirements exactly.",
            },
            {
                "role": "user",
                "content": "Translate this block.",
            },
        ],
    }


def test_extract_response_text_raises_when_max_output_is_hit():
    response_json = {
        "choices": [
            {
                "finish_reason": "length",
                "message": {
                    "content": "partial",
                },
            }
        ]
    }

    with pytest.raises(ValueError, match="max_tokens"):
        translate_md.extract_response_text(response_json)


def test_extract_response_text_reads_chat_completion_message():
    response_json = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": "翻译结果",
                },
            }
        ]
    }

    assert translate_md.extract_response_text(response_json) == "翻译结果"


def test_load_api_key_reads_deepseek_key_from_codex_env(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("DEEPSEEK_API_KEY=sk-test-key\n", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.setattr(translate_md, "CODEX_ENV_PATH", Path(env_path))

    assert translate_md.load_api_key() == "sk-test-key"


def test_load_api_key_prefers_file_deepseek_key_over_env_ark_key(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("DEEPSEEK_API_KEY=sk-file-key\n", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("ARK_API_KEY", "sk-env-ark-key")
    monkeypatch.setattr(translate_md, "CODEX_ENV_PATH", Path(env_path))

    assert translate_md.load_api_key() == "sk-file-key"


def test_translate_block_batch_groups_ten_short_blocks_into_one_request():
    markdown_blocks = [f"Paragraph {index}" for index in range(10)]
    request_prompts = []

    def fake_request_translation(prompt_text):
        request_prompts.append(prompt_text)
        source_text = translate_md.split_translation_prompt(prompt_text)
        group_size = source_text.count(translate_md.GROUP_SEPARATOR) + 1
        return f"\n\n{translate_md.GROUP_SEPARATOR}\n\n".join(
            f"译文 {index}" for index in range(group_size)
        )

    next_index, output_blocks = translate_md.translate_block_batch(
        0,
        markdown_blocks,
        fake_request_translation,
        max_workers=1,
        max_group_blocks=12,
    )

    assert next_index == 10
    assert len(request_prompts) == 1
    assert [translated for _, translated in output_blocks] == [f"译文 {index}" for index in range(10)]


def test_translate_block_batch_respects_max_group_blocks():
    markdown_blocks = [f"Paragraph {index}" for index in range(5)]
    request_prompts = []

    def fake_request_translation(prompt_text):
        request_prompts.append(prompt_text)
        source_text = translate_md.split_translation_prompt(prompt_text)
        group_size = source_text.count(translate_md.GROUP_SEPARATOR) + 1
        return f"\n\n{translate_md.GROUP_SEPARATOR}\n\n".join(
            f"译文 {index}" for index in range(group_size)
        )

    next_index, output_blocks = translate_md.translate_block_batch(
        0,
        markdown_blocks,
        fake_request_translation,
        max_workers=1,
        max_group_blocks=2,
    )

    assert next_index == 2
    assert len(request_prompts) == 1
    assert [translated for _, translated in output_blocks] == ["译文 0", "译文 1"]


def test_request_translation_retries_http_307_then_succeeds(monkeypatch):
    response_body = io.BytesIO(
        json.dumps(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "翻译成功"},
                    }
                ]
            }
        ).encode("utf-8")
    )

    class FakeResponse:
        def __enter__(self):
            return response_body

        def __exit__(self, exc_type, exc, tb):
            return False

    attempts = {"count": 0}

    def fake_urlopen(_request, timeout):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise error.HTTPError(
                "https://api.deepseek.com/chat/completions",
                307,
                "Temporary Redirect",
                {},
                io.BytesIO(b"<html>307 Temporary Redirect</html>"),
            )
        return FakeResponse()

    monkeypatch.setattr(translate_md, "load_api_key", lambda: "sk-test-key")
    monkeypatch.setattr(translate_md.request, "urlopen", fake_urlopen)

    translated_text = translate_md.request_translation(
        "Translate this block.",
        "deepseek-chat",
        "https://api.deepseek.com/chat/completions",
    )

    assert translated_text == "翻译成功"
    assert attempts["count"] == 2


def test_request_translation_retries_incomplete_read_then_succeeds(monkeypatch):
    response_body = io.BytesIO(
        json.dumps(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "翻译成功"},
                    }
                ]
            }
        ).encode("utf-8")
    )

    class FakeResponse:
        def __enter__(self):
            return response_body

        def __exit__(self, exc_type, exc, tb):
            return False

    attempts = {"count": 0}

    def fake_urlopen(_request, timeout):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise translate_md.http.client.IncompleteRead(b"partial")
        return FakeResponse()

    monkeypatch.setattr(translate_md, "load_api_key", lambda: "sk-test-key")
    monkeypatch.setattr(translate_md.request, "urlopen", fake_urlopen)

    translated_text = translate_md.request_translation(
        "Translate this block.",
        "deepseek-chat",
        "https://api.deepseek.com/chat/completions",
    )

    assert translated_text == "翻译成功"
    assert attempts["count"] == 2
