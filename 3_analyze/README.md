# 工程 3: コードベース影響分析 (Analyze)

## 目的

2_fetch で取得した変更情報を元に、対象コードベースへの影響を分析し、該当箇所とコンテキストを含むレポートを生成する。

## 入力

- `input/` ディレクトリ内の JSON ファイル（2_fetch の出力をコピー）
- または `--changes` オプションで直接指定

### 入力ファイルの形式

2_fetch の出力形式（推奨）:
```json
{
  "middleware": "php",
  "current": "8.2",
  "target": "8.5",
  "sources": [
    {
      "source": "local",
      "breaking_changes": [
        {
          "type": "deprecation",
          "description": "...",
          "pattern": "regex_pattern",
          "replacement": "..."
        }
      ]
    }
  ]
}
```

## 出力

`output/` ディレクトリに以下のファイルを生成:

- `impact-{middleware}-{timestamp}.json` - 機械処理用の構造化データ
- `impact_report.md` - 人間確認用のマークダウン形式

### JSON出力の構造

```json
{
  "analyze_timestamp": "2024-01-13T12:00:00+00:00",
  "codebase": "/path/to/project",
  "middleware": "php",
  "summary": {
    "total_changes": 25,
    "changes_with_matches": 5,
    "total_affected_files": 12,
    "total_matches": 45
  },
  "results": [
    {
      "change": { ... },
      "affected_files": ["file1.php", "file2.php"],
      "match_count": 3,
      "matches": [
        {
          "file": "src/example.php",
          "line": 42,
          "content": "matched line content",
          "context_before": ["line 39", "line 40", "line 41"],
          "context_after": ["line 43", "line 44", "line 45"]
        }
      ],
      "ai_analysis": "..."
    }
  ]
}
```

## 実行方法

```bash
cd 3_analyze

# 基本的な使い方（input/ から読み込み）
cp ../2_fetch/output/changes-*.json input/
uv run python run.py --codebase /path/to/your/project

# 変更ファイルを直接指定
uv run python run.py --codebase /path/to/project --changes ../2_fetch/output/changes-php-20240113.json

# ミドルウェアタイプを明示（ファイルフィルタ用）
uv run python run.py --codebase /path/to/project --middleware php

# AI分析を有効化（Claude API）
export ANTHROPIC_API_KEY=your_api_key
uv run python run.py --codebase /path/to/project --ai api

# Claude Code 用のプロンプトを出力
uv run python run.py --codebase /path/to/project --ai claude-code

# 出力先を変更
uv run python run.py --codebase /path/to/project --output-dir ./custom_output
```

## オプション

| オプション | 短縮形 | 必須 | 説明 |
|-----------|--------|------|------|
| `--codebase` | `-p` | Yes | 分析対象のコードベースパス |
| `--changes` | `-c` | No | 入力JSONファイルパス（省略時は input/*.json） |
| `--middleware` | `-m` | No | ミドルウェアタイプ（ファイルフィルタ用） |
| `--ai` | - | No | AI分析モード: `api`, `claude-code`, `none` |
| `--api-key` | - | No | Anthropic APIキー（環境変数でも可） |
| `--output-dir` | `-o` | No | 出力ディレクトリ（デフォルト: output） |

## ミドルウェアタイプ

`--middleware` オプションで指定可能な値と、対応する検索対象ファイル拡張子:

| タイプ | 対象ファイル |
|--------|-------------|
| `php` | `.php`, `.phtml`, `.inc` |
| `laravel` | `.php`, `.blade.php`, `.phtml` |
| `python` | `.py`, `.pyw` |
| `django` | `.py`, `.html` |
| `node` | `.js`, `.ts`, `.mjs`, `.cjs` |
| `react` | `.js`, `.jsx`, `.ts`, `.tsx` |
| `vue` | `.vue`, `.js`, `.ts` |
| `java` | `.java` |
| `spring` | `.java`, `.xml`, `.properties`, `.yml`, `.yaml` |
| `mysql` | `.sql` |
| `postgresql` | `.sql` |
| `ruby` | `.rb`, `.erb` |
| `rails` | `.rb`, `.erb`, `.html.erb` |
| `go` | `.go` |
| `default` | 一般的なコードファイル |

## AI分析モード

### `--ai none` (デフォルト)
AI分析を行わず、パターンマッチングのみ実行。

### `--ai api`
Claude API を使用して各該当箇所を分析。

要件:
- `ANTHROPIC_API_KEY` 環境変数 または `--api-key` オプション
- `anthropic` パッケージ: `uv add anthropic`

### `--ai claude-code`
Claude Code で後から分析するためのプロンプトを生成。
レポートに該当ファイルと分析指示が含まれる。

## チェックリスト

### 実行前

- [ ] 2_fetch の出力を `input/` にコピーしたか、`--changes` で指定したか
- [ ] 対象コードベースのパスは正しいか
- [ ] コードベースへの読み取り権限があるか
- [ ] AI分析を使う場合、APIキーが設定されているか

### 実行後

- [ ] `impact_report.md` を確認
- [ ] 影響のある変更が正しく検出されているか
- [ ] 誤検知（false positive）がないか確認
- [ ] 次の工程（修正）に必要な情報が揃っているか

## 処理フロー

```
input/*.json または --changes
        │
        ▼
┌───────────────────────┐
│ JSONから変更リスト読込 │
└───────────────────────┘
        │
        ▼
┌───────────────────────┐
│ 各変更のpatternで     │
│ コードベースをgrep検索 │
└───────────────────────┘
        │
        ▼
┌───────────────────────┐
│ 該当箇所の            │
│ コンテキスト取得       │
└───────────────────────┘
        │
        ▼ (--ai オプション使用時)
┌───────────────────────┐
│ AI分析               │
│ (api/claude-code)    │
└───────────────────────┘
        │
        ▼
┌───────────────────────┐
│ JSON/Markdown出力    │
└───────────────────────┘
```

## トラブルシューティング

### 入力ファイルが見つからない

```
Error: No input files found in /path/to/3_analyze/input
```

解決方法:
```bash
# 2_fetch の出力をコピー
cp ../2_fetch/output/changes-*.json input/

# または直接指定
uv run python run.py --codebase /path --changes ../2_fetch/output/changes-php-xxx.json
```

### 検索がタイムアウト

```
Warning: Search timed out for pattern: ...
```

- 複雑すぎる正規表現パターンの可能性
- 大規模なコードベースの場合は `--middleware` で検索対象を絞る

### AI分析でエラー

```
Error: anthropic SDK not installed
```

解決方法:
```bash
uv add anthropic
```

```
API Error: Invalid API key
```

解決方法:
```bash
export ANTHROPIC_API_KEY=your_valid_api_key
```

### 該当箇所が見つからない

- 変更データに `pattern` フィールドがない可能性
- 正規表現パターンが対象コードにマッチしない
- `--middleware` の指定が間違っている（拡張子フィルタ）

## 次の工程

```bash
cd ../4_fix
uv run python run.py
```

分析結果を元に、影響を受けるコードの修正を行う。
