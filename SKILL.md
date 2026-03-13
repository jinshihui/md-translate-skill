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

The script requires `ARK_API_KEY`.

It looks for the key in this order:

1. current process environment
2. `%CODEX_HOME%\.env`
3. `~/.codex/.env`

Example:

```env
ARK_API_KEY=your_api_key_here
```

## Command

From the skill root:

```powershell
python .\scripts\translate_md.py --input-path papers\example.md
```

Optional output path:

```powershell
python .\scripts\translate_md.py `
  --input-path papers\example.md `
  --output-path papers\example_zh.md
```
