# 工程 2: 変更情報の取得 (Fetch)

## 目的

設定ファイルに基づき、ミドルウェアのバージョンアップに伴う変更情報を取得し、JSON + Markdown 形式で出力する。

## 入力

- `../1_config/config.toml` - ミドルウェア設定ファイル

## 出力

`output/` ディレクトリに以下を生成:

| ファイル | 用途 |
|----------|------|
| `changes-{middleware}-{timestamp}.json` | 機械処理用（次工程の入力） |
| `changes-{middleware}-{timestamp}.md` | 人間確認用レポート |

## 実行方法

```bash
cd 2_fetch
uv run python run.py

# オプション
uv run python run.py --no-web         # ローカルデータのみ使用
uv run python run.py --output-dir=./out  # 出力先を変更
```

## チェックリスト

次工程に進む前に、以下を確認してください:

- [ ] `.md` ファイルを開き、取得した変更内容を確認した
- [ ] 不要な変更があれば `.json` から手動で削除した
- [ ] 変更の件数が妥当か確認した（多すぎる/少なすぎないか）
- [ ] 重要な破壊的変更がリストに含まれているか確認した

**重要**: `.md` ファイルは人間が内容を確認するためのレポートです。内容を確認し、必要に応じて `.json` を編集してから次工程に進んでください。

## 次の工程

確認が完了したら `3_analyze/` に進む:

```bash
cd ../3_analyze
uv run python run.py
```
