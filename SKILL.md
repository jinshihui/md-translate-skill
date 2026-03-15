---
name: md-bilingual-translate
description: Translate one Markdown file into a bilingual Markdown file with each original block followed by Simplified Chinese. Preserve formulas and code blocks. Run with plain Python.
---

# Markdown Bilingual Translate

Use this skill when you need to translate one Markdown file into Simplified Chinese while keeping bilingual Markdown output.

## What It Does

- Input: one `.md` file
- Output: a new `.md` file
- For each translatable block:
  - keep the original block first
  - put the Chinese translation directly below it
- Preserve formulas and fenced code blocks

## Runtime

- Main script: `scripts/translate_md.py`
- No extra package is required
- Run with plain Python 3.8+

## API Key

The script requires `DEEPSEEK_API_KEY`.

It looks for the key in this order:

1. `DEEPSEEK_API_KEY` in the current process environment
2. `DEEPSEEK_API_KEY` in `%CODEX_HOME%\.env`
3. `ARK_API_KEY` in the current process environment or `%CODEX_HOME%\.env` as a backward-compatible fallback

Example:

```env
DEEPSEEK_API_KEY=sk-your_api_key_here
```

## Default API Settings

- API URL: `https://api.deepseek.com/chat/completions`
- Model: `deepseek-chat`
- Default max workers: `40`
- Default max grouped blocks per request: `2`
- Max grouped input characters per request: `24000`
- Max output tokens per request: `8192`

## Command

From the skill root:

```powershell
python .\scripts\translate_md.py --input-path papers\example.md
```

This now defaults to the measured speed-oriented configuration:

- `--max-workers 40`
- `--max-group-blocks 2`

Optional output path:

```powershell
python .\scripts\translate_md.py `
  --input-path papers\example.md `
  --output-path papers\example_zh.md
```
