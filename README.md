# mw-auto-updater

ミドルウェアのバージョンアップグレード時に必要な変更点を自動で抽出・分析するツール。

## 概要

PHP、Laravel、MySQL などのミドルウェアをアップグレードする際の調査作業を支援するツールです。

**3つの独立した工程**で構成されており、各工程の間で人間がレビュー・判断を行います：

1. **設定**（人間が実施） - ミドルウェア名、現在バージョン、ターゲットバージョンを `config.toml` に記述
2. **変更を取得**（AIが実施） - 破壊的変更・非推奨・削除された機能を収集 → **レビュー**
3. **影響分析**（AIが実施） - 既存コードベースへの影響を検出 → **レビュー**

**特徴:**
- 指定した複数のデータソース（GitHub公式ドキュメント、php.watch、ローカルTOML）から変更情報を収集
- データソースごとに独立した出力を維持し、比較・検証が容易なレビュー体験を提供
- 人間によるレビュー工程を含む安全なワークフロー
- パターンマッチングによるコードベース影響分析
- 各工程でMarkdownレポートを出力

## 工程フロー

```
                    mw-auto-updater ワークフロー
    ========================================================

    [1_config]              [2_fetch]               [3_analyze]
   ┌──────────┐           ┌───────────┐           ┌───────────┐
   │  設定    │           │ 変更取得  │           │ 影響分析  │
   │          │   ───►    │           │   ───►    │           │
   │config.toml│          │ GitHub    │           │ codebase  │
   │          │           │ php.watch │           │ 検索      │
   │          │           │ local TOML│           │           │
   └──────────┘           └───────────┘           └───────────┘
        │                      │                       │
        ▼                      ▼                       ▼
   config.toml            output/*.json           output/*.json
   (検証済み)              output/*.md             output/*.md
                               │                       │
                    ┌──────────┴──────────┐            │
                    │  人間レビュー       │            │
                    │  - 変更内容を確認   │            │
                    │  - 不要項目を除外   │            │
                    └─────────────────────┘            │
                                            ┌──────────┴──────────┐
                                            │  人間レビュー       │
                                            │  - 影響箇所を確認   │
                                            │  - 修正方針を決定   │
                                            └─────────────────────┘
```

**ポイント:** 各工程はコマンドで手動実行します。工程間で人間がレビューを行い、次の工程に進むか判断します。

## クイックスタート

### 1. 設定 (1_config)

```bash
cd 1_config

# config.toml を編集（対象ミドルウェアとバージョンを設定）
vim config.toml

# 設定を検証
uv run python run.py
```

**チェックポイント:**
- 対象ミドルウェア名は正しいか
- 現在バージョン (current) は正確か
- ターゲットバージョン (target) は妥当か

---

### 2. 変更取得 (2_fetch)

```bash
cd 2_fetch

# 変更情報を取得（GitHub, php.watch, ローカルデータから収集）
uv run python run.py

# ローカルデータのみ使用する場合
uv run python run.py --no-web
```

**出力ファイル:**
- `output/changes-{middleware}-{timestamp}.json` - 機械処理用データ
- `output/changes-{middleware}-{timestamp}.md` - 人間確認用レポート

**チェックポイント:**
- 出力された `.md` ファイルを確認
- 破壊的変更 (breaking) の数を把握
- プロジェクトに無関係な変更を特定

---

### 3. 影響分析 (3_analyze)

```bash
cd 3_analyze

# 2_fetch の出力を input/ にコピー
cp ../2_fetch/output/changes-*.json input/

# コードベースを分析
uv run python run.py --codebase /path/to/your/project
```

**出力ファイル:**
- `output/impact-{middleware}-{timestamp}.json` - 影響分析データ
- `output/impact-{middleware}-{timestamp}.md` - 影響分析レポート

**チェックポイント:**
- 影響を受けるファイル数を確認
- パターンマッチの結果が妥当か
- 修正が必要な箇所を把握

## 人間チェックポイントの説明

このツールは完全自動化ではなく、人間の判断を挟む設計です。

### 2_fetch 後のレビュー

2_fetch で取得した変更情報には、プロジェクトに無関係な項目が含まれる場合があります。

| 変更タイプ | 説明 | 推奨アクション |
|-----------|------|---------------|
| `breaking` | 破壊的変更 | 必ず確認 |
| `removed` | 削除された機能 | 必ず確認 |
| `deprecation` | 非推奨化 | 個別に判断 |
| `new` | 新機能 | 参考情報として確認 |

### 3_analyze 後のレビュー

影響分析の結果を確認し、実際の修正作業に進みます。

- パターンマッチで検出された箇所が実際に影響を受けるか確認
- 誤検出（false positive）を除外
- 修正の優先順位を決定

## ディレクトリ構成

```
mw-auto-updater/
├── 1_config/                 # 工程1: 設定
│   ├── README.md
│   ├── config.toml           # ミドルウェア設定ファイル
│   └── run.py                # 設定検証スクリプト
│
├── 2_fetch/                  # 工程2: 変更情報の取得
│   ├── README.md
│   ├── run.py                # メイン取得スクリプト
│   ├── data/                 # ローカル変更データ (TOML)
│   │   ├── php-8.3-changes.toml
│   │   ├── php-8.4-changes.toml
│   │   └── php-8.5-changes.toml
│   └── output/               # 出力（JSON, Markdown）
│
├── 3_analyze/                # 工程3: 影響分析
│   ├── README.md
│   ├── run.py                # 影響分析スクリプト
│   ├── input/                # 2_fetch からの入力
│   └── output/               # 出力（JSON, Markdown）
│
├── legacy/                   # 旧スクリプト（参考用）
│   ├── mw_upgrade_check.py   # 旧メインスクリプト
│   ├── analyze_impact.py     # 旧影響分析スクリプト
│   └── php-upgrade-check.sh  # 旧シェルスクリプト
│
├── pyproject.toml            # Python プロジェクト設定
└── README.md                 # このファイル
```

## インストール

```bash
git clone https://github.com/mister-X-is-your-father/mw-auto-updater.git
cd mw-auto-updater

# uv で仮想環境セットアップ
uv sync
```

**依存:**
- Python 3.9+
- [uv](https://docs.astral.sh/uv/) (推奨)

## 対応ミドルウェア

| Name | Status | データソース |
|------|--------|-------------|
| PHP  | 対応済み | github, php.watch, local |
| Laravel | 計画中 | - |
| MySQL | 計画中 | - |

## ライセンス

MIT
