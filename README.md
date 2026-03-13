# Markdown Bilingual Translate

[中文说明](./README.zh-CN.md)

This repo is a minimal Codex skill.

The public runtime is just one script:

- `scripts/translate_md.py`

It translates one Markdown file into a bilingual Markdown file:

- original block
- Simplified Chinese translation right below it

Formulas and fenced code blocks are preserved.

![alt text](00assets/image-1.png)

## Requirements

- Python 3.8+
- `ARK_API_KEY`

No extra package is required.

The script reads `ARK_API_KEY` from:

1. the current environment
2. `%CODEX_HOME%\.env`
3. `~/.codex/.env`

Example:

```env
ARK_API_KEY=your_api_key_here
```

## Usage

```powershell
python .\scripts\translate_md.py --input-path papers\example.md
```

Optional output path:

```powershell
python .\scripts\translate_md.py `
  --input-path papers\example.md `
  --output-path papers\example_zh.md
```

Default output files:

- `papers/example_zh.md`
- `papers/example_zh.md.metrics.json`

The script may also create a temporary progress file during translation and remove it after success.
