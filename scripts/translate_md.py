import argparse
import http.client
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib import error, request


API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_SOURCE_LANGUAGE = "auto"
DEFAULT_TARGET_LANGUAGE = "Simplified Chinese"
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
CODEX_ENV_PATH = CODEX_HOME / ".env"
REQUEST_TIMEOUT_SECONDS = 120
MAX_RETRIES = 3
PROGRESS_SUFFIX = ".progress.json"
METRICS_SUFFIX = ".metrics.json"
DEFAULT_MAX_WORKERS = 40
DEFAULT_MAX_GROUP_BLOCKS = 2
DEFAULT_MAX_GROUP_CHARACTERS = 24000
DEFAULT_MAX_OUTPUT_TOKENS = 8192
LANGUAGE_CODE_MAP = {
    "auto": "auto",
    "english": "en",
    "en": "en",
    "french": "fr",
    "fr": "fr",
    "simplified chinese": "zh",
    "chinese": "zh",
    "zh": "zh",
    "zh-cn": "zh",
}
LANGUAGE_STOPWORDS = {
    "en": {
        "the", "and", "of", "in", "to", "with", "for", "on", "is", "are",
        "this", "that", "between", "paper", "abstract", "geometry",
    },
    "fr": {
        "le", "la", "les", "de", "des", "du", "une", "un", "et", "dans",
        "pour", "avec", "sur", "entre", "cet", "cette", "article", "résumé",
        "geometrie", "géométrie",
    },
}
GROUP_SEPARATOR = "<!--MD_TRANSLATE_SEPARATOR-->"
SINGLE_BLOCK_PROMPT_TEMPLATE = """Translate the following Markdown block from English to Simplified Chinese.

Requirements:
- Keep Markdown syntax if the block includes headings, list markers, or table pipes.
- Output only the Chinese translation for this block.
- Use precise academic terminology.
- Preserve all formulas exactly, including content inside $, $$, \\( \\), and \\[ \\].
- Do not add explanations, notes, or extra markup.

Markdown block:
{block}
"""
GROUP_PROMPT_TEMPLATE = """Translate the following Markdown content from English to Simplified Chinese.

Requirements:
- Keep Markdown syntax if the content includes headings, list markers, or table pipes.
- Keep every {separator} line exactly unchanged.
- Use precise academic terminology.
- Preserve all formulas exactly, including content inside $, $$, \\( \\), and \\[ \\].
- Do not add explanations, notes, or extra markup.

Markdown content:
{block}
"""


def split_translation_prompt(prompt_text):
    for separator in ("\nMarkdown content:\n", "\nMarkdown block:\n"):
        if separator in prompt_text:
            return prompt_text.split(separator, 1)[1].rstrip()
    return prompt_text.rstrip()


def normalize_translation_language(language):
    normalized_language = language.strip().lower()
    return LANGUAGE_CODE_MAP.get(normalized_language, language)


def detect_source_language(markdown_blocks, max_blocks=20, max_characters=6000):
    sample_parts = []
    total_characters = 0
    for markdown_block in markdown_blocks:
        if is_passthrough_block(markdown_block):
            continue
        sample_parts.append(markdown_block)
        total_characters += len(markdown_block)
        if len(sample_parts) >= max_blocks or total_characters >= max_characters:
            break

    sample_text = "\n".join(sample_parts)
    if not sample_text.strip():
        return "en"

    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", sample_text))
    if cjk_count >= max(20, len(sample_text) // 20):
        return "zh"

    normalized_text = sample_text.lower()
    tokens = re.findall(r"[a-zA-ZÀ-ÿ]+", normalized_text)
    accent_count = len(re.findall(r"[àâæçéèêëîïôœùûüÿ]", normalized_text))
    scores = {
        language: sum(1 for token in tokens if token in stopwords)
        for language, stopwords in LANGUAGE_STOPWORDS.items()
    }
    scores["fr"] += accent_count * 2
    if scores["fr"] > scores["en"]:
        return "fr"
    return "en"


def build_request_payload(prompt_text, model, source_language, target_language):
    return {
        "model": model,
        "stream": False,
        "max_tokens": DEFAULT_MAX_OUTPUT_TOKENS,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a professional academic translator. "
                    "Follow the user's Markdown preservation requirements exactly."
                ),
            },
            {
                "role": "user",
                "content": prompt_text,
            },
        ],
    }


def load_api_key():
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if api_key:
        return api_key

    if CODEX_ENV_PATH.exists():
        for line in CODEX_ENV_PATH.read_text(encoding="utf-8").splitlines():
            stripped_line = line.strip()
            if stripped_line.startswith("DEEPSEEK_API_KEY="):
                return stripped_line.split("=", 1)[1].strip().strip('"').strip("'")

    api_key = os.environ.get("ARK_API_KEY")
    if api_key:
        return api_key

    if CODEX_ENV_PATH.exists():
        for line in CODEX_ENV_PATH.read_text(encoding="utf-8").splitlines():
            stripped_line = line.strip()
            if stripped_line.startswith("ARK_API_KEY="):
                return stripped_line.split("=", 1)[1].strip().strip('"').strip("'")

    raise ValueError(
        "DEEPSEEK_API_KEY is required. "
        f"Set it in the environment or add it to {CODEX_ENV_PATH}."
    )


def split_markdown_blocks(markdown_text):
    blocks = []
    current_lines = []
    fence_marker = None

    for line in markdown_text.splitlines():
        stripped_line = line.strip()
        if fence_marker:
            current_lines.append(line)
            if stripped_line.startswith(fence_marker):
                blocks.append("\n".join(current_lines).rstrip())
                current_lines = []
                fence_marker = None
            continue
        if stripped_line.startswith("```") or stripped_line.startswith("~~~"):
            if current_lines:
                blocks.append("\n".join(current_lines).rstrip())
                current_lines = []
            current_lines.append(line)
            fence_marker = stripped_line[:3]
            continue
        if not stripped_line:
            if current_lines:
                blocks.append("\n".join(current_lines).rstrip())
                current_lines = []
            continue
        current_lines.append(line)

    if current_lines:
        blocks.append("\n".join(current_lines).rstrip())
    return blocks


def is_passthrough_block(markdown_block):
    stripped_block = markdown_block.strip()
    if stripped_block.startswith("```") or stripped_block.startswith("~~~"):
        return True
    if stripped_block in {"---", "***", "___"}:
        return True
    if re.fullmatch(r"!\[[^\]]*\]\([^)]+\)", stripped_block):
        return True
    if re.fullmatch(r"\$\$[\s\S]*\$\$", stripped_block):
        return True
    if re.fullmatch(r"\\\[[\s\S]*\\\]", stripped_block):
        return True
    return False


def extract_response_text(response_json):
    choices = response_json.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if first_choice.get("finish_reason") == "length":
            raise ValueError("Response was truncated because it reached max_tokens.")

        message = first_choice.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                text_list = []
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") == "text" and isinstance(item.get("text"), str):
                        text_list.append(item["text"].strip())
                if text_list:
                    return "\n".join(text_list)

    output_text = response_json.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    text_list = []
    for item in response_json.get("output", []):
        for content_item in item.get("content", []):
            text_value = content_item.get("text")
            if isinstance(text_value, str) and text_value.strip():
                text_list.append(text_value.strip())
            if isinstance(text_value, dict):
                nested_value = text_value.get("value") or text_value.get("text")
                if isinstance(nested_value, str) and nested_value.strip():
                    text_list.append(nested_value.strip())

    if text_list:
        return "\n".join(text_list)
    raise ValueError("Response JSON did not contain translated text.")


def extract_response_usage(response_json):
    usage = response_json.get("usage")
    if not isinstance(usage, dict):
        return {}

    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    total_tokens = usage.get("total_tokens")
    input_details = usage.get("input_tokens_details")
    output_details = usage.get("output_tokens_details")
    cached_tokens = None
    reasoning_tokens = None

    if isinstance(input_details, dict):
        cached_tokens = input_details.get("cached_tokens")
    elif isinstance(usage.get("prompt_tokens_details"), dict):
        cached_tokens = usage["prompt_tokens_details"].get("cached_tokens")

    if isinstance(output_details, dict):
        reasoning_tokens = output_details.get("reasoning_tokens")
    elif isinstance(usage.get("completion_tokens_details"), dict):
        reasoning_tokens = usage["completion_tokens_details"].get("reasoning_tokens")

    if total_tokens is None and isinstance(input_tokens, int) and isinstance(output_tokens, int):
        total_tokens = input_tokens + output_tokens

    normalized_usage = {}
    for key, value in {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cached_input_tokens": cached_tokens,
        "reasoning_output_tokens": reasoning_tokens,
    }.items():
        if isinstance(value, int):
            normalized_usage[key] = value
    return normalized_usage


def build_404_error_message(model, detail):
    return (
        f"DeepSeek API request failed with status 404 for model '{model}': {detail}\n"
        "排查方向：\n"
        "1. 确认模型 ID 是否正确，例如 deepseek-chat。\n"
        "2. 确认 base URL 是否仍是 https://api.deepseek.com/chat/completions。\n"
        "3. 确认 API key 已开通，并且 Authorization 头使用 Bearer 格式。"
    )


def split_group_translation(translated_text, expected_count):
    translated_parts = [part.strip() for part in translated_text.split(GROUP_SEPARATOR)]
    if len(translated_parts) != expected_count or any(not part for part in translated_parts):
        raise ValueError("Group separator mismatch")
    return translated_parts


def request_translation(
    prompt_text,
    model,
    api_url,
    source_language=DEFAULT_SOURCE_LANGUAGE,
    target_language=DEFAULT_TARGET_LANGUAGE,
    request_metrics_callback=None,
):
    api_key = load_api_key()
    payload = build_request_payload(prompt_text, model, source_language, target_language)
    request_body = json.dumps(payload).encode("utf-8")
    source_text = split_translation_prompt(prompt_text)
    api_request = request.Request(
        api_url,
        data=request_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    for attempt in range(MAX_RETRIES):
        request_start = time.perf_counter()
        try:
            with request.urlopen(api_request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                response_json = json.load(response)
                translated_text = extract_response_text(response_json)
                if request_metrics_callback is not None:
                    request_metrics_callback(
                        {
                            "ok": True,
                            "attempt": attempt + 1,
                            "model": model,
                            "prompt_characters": len(prompt_text),
                            "source_characters": len(source_text),
                            "elapsed_seconds": round(time.perf_counter() - request_start, 3),
                            **extract_response_usage(response_json),
                        }
                    )
                return translated_text
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if request_metrics_callback is not None:
                request_metrics_callback(
                    {
                        "ok": False,
                        "attempt": attempt + 1,
                        "model": model,
                        "prompt_characters": len(prompt_text),
                        "source_characters": len(source_text),
                        "elapsed_seconds": round(time.perf_counter() - request_start, 3),
                        "error_type": "HTTPError",
                        "status_code": exc.code,
                        "error_detail": detail[:500],
                    }
                )
            if exc.code == 404:
                raise RuntimeError(build_404_error_message(model, detail)) from exc
            if exc.code in {307, 308} and attempt < MAX_RETRIES - 1:
                time.sleep(attempt + 1)
                continue
            if 500 <= exc.code < 600 and attempt < MAX_RETRIES - 1:
                time.sleep(attempt + 1)
                continue
            raise RuntimeError(f"DeepSeek API request failed with status {exc.code}: {detail}") from exc
        except (error.URLError, http.client.RemoteDisconnected, http.client.IncompleteRead, TimeoutError) as exc:
            if request_metrics_callback is not None:
                request_metrics_callback(
                    {
                        "ok": False,
                        "attempt": attempt + 1,
                        "model": model,
                        "prompt_characters": len(prompt_text),
                        "source_characters": len(source_text),
                        "elapsed_seconds": round(time.perf_counter() - request_start, 3),
                        "error_type": type(exc).__name__,
                        "error_detail": str(exc),
                    }
                )
            if attempt == MAX_RETRIES - 1:
                raise RuntimeError(f"DeepSeek API request failed after {MAX_RETRIES} attempts: {exc}") from exc
            time.sleep(attempt + 1)


def translate_block_batch(
    start_index,
    markdown_blocks,
    request_translation_fn,
    max_workers=DEFAULT_MAX_WORKERS,
    max_group_blocks=DEFAULT_MAX_GROUP_BLOCKS,
    max_group_characters=DEFAULT_MAX_GROUP_CHARACTERS,
    event_log=None,
):
    markdown_block = markdown_blocks[start_index]
    if is_passthrough_block(markdown_block):
        return start_index + 1, [(markdown_block, None)]

    batch_items = []
    translation_groups = []
    next_index = start_index

    while next_index < len(markdown_blocks):
        markdown_block = markdown_blocks[next_index]
        needs_translation = not is_passthrough_block(markdown_block)
        batch_items.append((next_index, markdown_block, needs_translation))
        if not needs_translation:
            next_index += 1
            continue

        if (
            not translation_groups
            or batch_items[-2][2] is False
            or len(translation_groups[-1]) >= max_group_blocks
            or sum(len(block_text) for _, block_text in translation_groups[-1]) + len(markdown_block)
            > max_group_characters
        ):
            if len(translation_groups) >= max_workers:
                batch_items.pop()
                break
            translation_groups.append([])
        translation_groups[-1].append((next_index, markdown_block))
        next_index += 1

    if translation_groups:
        print(
            f"Translating blocks {batch_items[0][0] + 1}-{batch_items[-1][0] + 1}/{len(markdown_blocks)}...",
            flush=True,
        )
    group_characters = [sum(len(block_text) for _, block_text in group) for group in translation_groups]

    def translate_group(group_with_characters):
        group, total_characters = group_with_characters
        if len(group) == 1:
            index, block_text = group[0]
            translated_block = request_translation_fn(SINGLE_BLOCK_PROMPT_TEMPLATE.format(block=block_text)).strip()
            return {index: translated_block}

        merged_text = f"\n\n{GROUP_SEPARATOR}\n\n".join(block_text for _, block_text in group)
        try:
            translated_text = request_translation_fn(
                GROUP_PROMPT_TEMPLATE.format(separator=GROUP_SEPARATOR, block=merged_text)
            ).strip()
            translated_parts = split_group_translation(translated_text, len(group))
            return {
                index: translated_part
                for (index, _), translated_part in zip(group, translated_parts)
            }
        except Exception as exc:
            if event_log is not None:
                event_log.append(
                    {
                        "event": "group_fallback",
                        "start_block": group[0][0] + 1,
                        "end_block": group[-1][0] + 1,
                        "group_size": len(group),
                        "group_characters": total_characters,
                        "reason": str(exc),
                    }
                )
            print(
                f"Grouped translation failed at blocks {group[0][0] + 1}-{group[-1][0] + 1}; retrying individually: {exc}",
                flush=True,
            )
            return {
                index: request_translation_fn(SINGLE_BLOCK_PROMPT_TEMPLATE.format(block=block_text)).strip()
                for index, block_text in group
            }

    translation_by_index = {}
    if len(translation_groups) == 1 or max_workers == 1:
        for group_with_characters in zip(translation_groups, group_characters):
            translation_by_index.update(translate_group(group_with_characters))
    elif translation_groups:
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for translated_group in executor.map(translate_group, zip(translation_groups, group_characters)):
                    translation_by_index.update(translated_group)
        except Exception as exc:
            if event_log is not None:
                event_log.append(
                    {
                        "event": "parallel_window_retry_serial",
                        "start_block": batch_items[0][0] + 1,
                        "end_block": batch_items[-1][0] + 1,
                        "reason": str(exc),
                    }
                )
            print(
                f"Parallel translation failed for blocks {batch_items[0][0] + 1}-{batch_items[-1][0] + 1}; retrying serially: {exc}",
                flush=True,
            )
            translation_by_index = {}
            for group_with_characters in zip(translation_groups, group_characters):
                translation_by_index.update(translate_group(group_with_characters))

    return next_index, [
        (markdown_block, translation_by_index.get(index) if needs_translation else None)
        for index, markdown_block, needs_translation in batch_items
    ]


def translate_markdown_text(
    markdown_text,
    request_translation_fn,
    max_workers=DEFAULT_MAX_WORKERS,
    max_group_blocks=DEFAULT_MAX_GROUP_BLOCKS,
    max_group_characters=DEFAULT_MAX_GROUP_CHARACTERS,
    event_log=None,
):
    bilingual_blocks = []
    markdown_blocks = split_markdown_blocks(markdown_text)
    block_index = 0
    while block_index < len(markdown_blocks):
        next_block_index, output_blocks = translate_block_batch(
            block_index,
            markdown_blocks,
            request_translation_fn,
            max_workers=max_workers,
            max_group_blocks=max_group_blocks,
            max_group_characters=max_group_characters,
            event_log=event_log,
        )
        for markdown_block, translated_block in output_blocks:
            bilingual_blocks.append(markdown_block)
            if translated_block is not None:
                bilingual_blocks.append(translated_block)
        block_index = next_block_index
    return "\n\n".join(bilingual_blocks).rstrip() + "\n"


def translate_markdown_file(
    source_path,
    output_path,
    request_translation_fn,
    max_workers=DEFAULT_MAX_WORKERS,
    max_group_blocks=DEFAULT_MAX_GROUP_BLOCKS,
    max_group_characters=DEFAULT_MAX_GROUP_CHARACTERS,
    event_log=None,
):
    source_path = Path(source_path)
    output_path = Path(output_path)
    progress_path = output_path.with_name(f"{output_path.name}{PROGRESS_SUFFIX}")
    markdown_blocks = split_markdown_blocks(source_path.read_text(encoding="utf-8"))
    total_blocks = len(markdown_blocks)
    next_block_index = 0

    if progress_path.exists() and output_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        if (
            progress.get("source_path") == str(source_path.resolve())
            and progress.get("output_path") == str(output_path.resolve())
            and progress.get("total_blocks") == total_blocks
        ):
            next_block_index = min(progress.get("next_block_index", 0), total_blocks)

    if next_block_index and output_path.exists():
        output_path.write_text(output_path.read_text(encoding="utf-8").rstrip("\n"), encoding="utf-8")

    file_mode = "a" if next_block_index and output_path.exists() else "w"
    with output_path.open(file_mode, encoding="utf-8") as output_file:
        block_index = next_block_index
        while block_index < total_blocks:
            try:
                next_block_index, output_blocks = translate_block_batch(
                    block_index,
                    markdown_blocks,
                    request_translation_fn,
                    max_workers=max_workers,
                    max_group_blocks=max_group_blocks,
                    max_group_characters=max_group_characters,
                    event_log=event_log,
                )
            except Exception as exc:
                progress_path.write_text(
                    json.dumps(
                        {
                            "source_path": str(source_path.resolve()),
                            "output_path": str(output_path.resolve()),
                            "total_blocks": total_blocks,
                            "next_block_index": block_index,
                            "failed_block_index": block_index,
                            "failed_block_preview": markdown_blocks[block_index][:160],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                raise RuntimeError(f"Translation failed at block {block_index + 1}/{total_blocks}: {exc}") from exc

            for current_index, (markdown_block, translated_block) in enumerate(output_blocks, start=block_index):
                if current_index > 0:
                    output_file.write("\n\n")
                output_file.write(markdown_block)
                if translated_block is not None:
                    output_file.write("\n\n")
                    output_file.write(translated_block)
                output_file.flush()

                progress_path.write_text(
                    json.dumps(
                        {
                            "source_path": str(source_path.resolve()),
                            "output_path": str(output_path.resolve()),
                            "total_blocks": total_blocks,
                            "next_block_index": current_index + 1,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            block_index = next_block_index

    current_output = output_path.read_text(encoding="utf-8")
    if current_output and not current_output.endswith("\n"):
        output_path.write_text(current_output + "\n", encoding="utf-8")
    progress_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Translate a Markdown file into bilingual English-Chinese output.")
    parser.add_argument("--input-path", required=True, help="Path to the source Markdown file.")
    parser.add_argument(
        "--output-path",
        help="Path to the translated Markdown file. Defaults to <input_stem>_zh.md.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="DeepSeek model id.")
    parser.add_argument("--api-url", default=API_URL, help="DeepSeek chat completions API URL.")
    parser.add_argument("--source-language", default=DEFAULT_SOURCE_LANGUAGE, help="Source language.")
    parser.add_argument("--target-language", default=DEFAULT_TARGET_LANGUAGE, help="Target language.")
    parser.add_argument(
        "--metrics-path",
        help="Optional JSON metrics path. Defaults to <output_name>.metrics.json.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help="Maximum number of Markdown blocks to translate concurrently.",
    )
    parser.add_argument(
        "--max-group-blocks",
        type=int,
        default=DEFAULT_MAX_GROUP_BLOCKS,
        help="Maximum number of translated Markdown blocks merged into one request.",
    )
    parser.add_argument(
        "--max-group-characters",
        type=int,
        default=DEFAULT_MAX_GROUP_CHARACTERS,
        help="Maximum number of source characters merged into one request.",
    )
    args = parser.parse_args()

    input_path = Path(args.input_path)
    output_path = Path(args.output_path) if args.output_path else input_path.with_name(f"{input_path.stem}_zh.md")
    metrics_path = Path(args.metrics_path) if args.metrics_path else output_path.with_name(
        f"{output_path.name}{METRICS_SUFFIX}"
    )
    markdown_blocks = split_markdown_blocks(input_path.read_text(encoding="utf-8"))
    source_language = args.source_language
    if normalize_translation_language(source_language) == "auto":
        source_language = detect_source_language(markdown_blocks)
        print(f"Detected source language: {source_language}", flush=True)

    run_started_at = time.perf_counter()
    request_metrics = []
    event_log = []
    run_status = "succeeded"
    run_error = None

    try:
        translate_markdown_file(
            input_path,
            output_path,
            lambda prompt_text: request_translation(
                prompt_text,
                args.model,
                args.api_url,
                source_language=source_language,
                target_language=args.target_language,
                request_metrics_callback=request_metrics.append,
            ),
            max_workers=args.max_workers,
            max_group_blocks=args.max_group_blocks,
            max_group_characters=args.max_group_characters,
            event_log=event_log,
        )
    except Exception as exc:
        run_status = "failed"
        run_error = str(exc)
        raise
    finally:
        total_elapsed_seconds = round(time.perf_counter() - run_started_at, 3)
        successful_requests = [item for item in request_metrics if item.get("ok")]
        metrics_report = {
            "status": run_status,
            "error": run_error,
            "source_path": str(input_path.resolve()),
            "output_path": str(output_path.resolve()),
            "model": args.model,
            "api_url": args.api_url,
            "source_language": source_language,
            "target_language": args.target_language,
            "max_workers": args.max_workers,
            "max_group_blocks": args.max_group_blocks,
            "max_group_characters": args.max_group_characters,
            "total_elapsed_seconds": total_elapsed_seconds,
            "request_summary": {
                "total_attempts": len(request_metrics),
                "successful_requests": len(successful_requests),
                "failed_attempts": len(request_metrics) - len(successful_requests),
                "requests_with_usage": sum(1 for item in successful_requests if "total_tokens" in item),
                "sum_request_seconds": round(
                    sum(item.get("elapsed_seconds", 0.0) for item in request_metrics),
                    3,
                ),
                "total_prompt_characters": sum(item.get("prompt_characters", 0) for item in request_metrics),
                "total_source_characters": sum(item.get("source_characters", 0) for item in request_metrics),
                "prompt_overhead_characters": sum(
                    item.get("prompt_characters", 0) - item.get("source_characters", 0)
                    for item in request_metrics
                ),
            },
            "token_summary": {
                "input_tokens": sum(item.get("input_tokens", 0) for item in successful_requests),
                "output_tokens": sum(item.get("output_tokens", 0) for item in successful_requests),
                "total_tokens": sum(item.get("total_tokens", 0) for item in successful_requests),
                "cached_input_tokens": sum(item.get("cached_input_tokens", 0) for item in successful_requests),
                "reasoning_output_tokens": sum(
                    item.get("reasoning_output_tokens", 0) for item in successful_requests
                ),
            },
            "event_summary": {
                "group_fallbacks": sum(1 for item in event_log if item.get("event") == "group_fallback"),
                "parallel_window_retries": sum(
                    1 for item in event_log if item.get("event") == "parallel_window_retry_serial"
                ),
            },
            "requests": request_metrics,
            "events": event_log,
        }
        metrics_path.write_text(
            json.dumps(metrics_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Metrics written to {metrics_path}", flush=True)


if __name__ == "__main__":
    main()
