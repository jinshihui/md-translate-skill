# Markdown Bilingual Translate

[中文说明](./README.zh-CN.md)

`md-bilingual-translate` is a Codex skill for turning one Markdown file into bilingual output.
For each translatable paragraph, it keeps the original text first and inserts the Simplified Chinese translation right below it.
Formulas, fenced code blocks, and image-only lines are preserved.

![Bilingual Markdown example](00assets/image-1.png)

## What This Is For

Use this skill when you want to:

- translate a paper or note written in Markdown
- keep the original text and the Chinese translation together
- avoid breaking formulas or code blocks during translation

This repo also works as a standalone script if you do not need Codex skill integration.

## Install

### Option 1: Install as a Codex skill

Clone or copy this repository to your Codex skills directory:

```powershell
git clone <your-repo-url> "$env:CODEX_HOME\skills\md-bilingual-translate"
```

If `CODEX_HOME` is not set, Codex usually uses `~/.codex`.

### Option 2: Run it as a plain script

Clone this repository anywhere in your workspace and run `scripts/translate_md.py` directly.

No extra Python package is required.

## Configure API Key

The translator requires `DEEPSEEK_API_KEY`.

It looks for the key in this order:

1. `DEEPSEEK_API_KEY` in the current environment
2. `DEEPSEEK_API_KEY` in `%CODEX_HOME%\.env`
3. `ARK_API_KEY` in the current environment or `%CODEX_HOME%\.env` as a backward-compatible fallback

Example:

```env
DEEPSEEK_API_KEY=sk-your_api_key_here
```

## Use It In Codex

After the skill is installed, ask Codex to use `$md-bilingual-translate` on a Markdown file.

Example request:

```text
Use $md-bilingual-translate to translate papers/example.md into bilingual Simplified Chinese Markdown.
```

## Use It From The Terminal

Run the script from the repository root:

```powershell
python .\scripts\translate_md.py --input-path papers\example.md
```

Optional output path:

```powershell
python .\scripts\translate_md.py `
  --input-path papers\example.md `
  --output-path papers\example_zh.md
```

## Output

By default, the script creates:

- `papers/example_zh.md`
- `papers/example_zh.md.metrics.json`

During translation it may also create a temporary progress file and remove it after a successful run.
