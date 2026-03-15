# Markdown Bilingual Translate

[English README](./README.md)

`md-bilingual-translate` 是一个 Codex Skill，用来把单个 Markdown 文件翻译成中英双语版本。
它会保留原文，并在每个可翻译段落后面紧跟一段简体中文译文。
公式、围栏代码块和纯图片行会原样保留。

![双语 Markdown 示例](00assets/image-1.png)

## 这个 Skill 能做什么

适合这些场景：

- 把 Markdown 格式的论文或笔记翻译成简体中文
- 希望原文和译文放在同一份文档里，方便对照阅读
- 希望尽量避免翻译过程破坏公式或代码块

如果你不需要 Codex Skill 集成，也可以把这个仓库当成普通脚本直接运行。

## 安装方式

### 方式一：安装为 Codex Skill

把这个仓库克隆或复制到 Codex 的 skills 目录：

```powershell
git clone <你的仓库地址> "$env:CODEX_HOME\skills\md-bilingual-translate"
```

如果没有设置 `CODEX_HOME`，Codex 一般会使用 `~/.codex`。

### 方式二：直接当脚本运行

把仓库放到任意工作目录，然后直接运行 `scripts/translate_md.py` 即可。

不需要额外安装第三方 Python 包。

## 配置 API Key

脚本依赖 `DEEPSEEK_API_KEY`。

读取顺序如下：

1. 当前环境变量里的 `DEEPSEEK_API_KEY`
2. `%CODEX_HOME%\.env` 里的 `DEEPSEEK_API_KEY`
3. 当前环境变量或 `%CODEX_HOME%\.env` 里的 `ARK_API_KEY`，仅作为兼容旧配置的回退

示例：

```env
DEEPSEEK_API_KEY=sk-your_api_key_here
```

## 在 Codex 里使用

安装完成后，可以直接在 Codex 里点名使用 `$md-bilingual-translate`。

示例：

```text
使用 $md-bilingual-translate 把 papers/example.md 翻译成简体中文双语 Markdown。
```

## 在终端里使用

在仓库根目录运行：

```powershell
python .\scripts\translate_md.py --input-path papers\example.md
```

如果想指定输出路径：

```powershell
python .\scripts\translate_md.py `
  --input-path papers\example.md `
  --output-path papers\example_zh.md
```

## 输出结果

默认会生成：

- `papers/example_zh.md`
- `papers/example_zh.md.metrics.json`

翻译过程中还可能生成临时进度文件，成功结束后会自动删除。
