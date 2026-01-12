#!/usr/bin/env python3
"""
工程 1: 設定検証
config.toml の内容を検証し、次工程で使用可能か確認する。
"""

import sys
from pathlib import Path

# Python 3.11+ has tomllib built-in
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        print("Error: tomli が必要です。`uv add tomli` を実行してください。")
        sys.exit(1)


def validate_config(config_path: Path) -> bool:
    """設定ファイルを検証"""
    if not config_path.exists():
        print(f"Error: 設定ファイルが見つかりません: {config_path}")
        return False

    try:
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
    except Exception as e:
        print(f"Error: TOML パースエラー: {e}")
        return False

    middlewares = config.get("middleware", [])
    if not middlewares:
        print("Error: [[middleware]] セクションがありません")
        return False

    valid = True
    for i, mw in enumerate(middlewares, 1):
        name = mw.get("name")
        current = mw.get("current")
        target = mw.get("target")
        sources = mw.get("sources", ["local"])

        print(f"\n[Middleware {i}]")
        print(f"  Name:    {name or '(未設定)'}")
        print(f"  Current: {current or '(未設定)'}")
        print(f"  Target:  {target or '(未設定)'}")
        print(f"  Sources: {sources}")

        if not name:
            print("  ⚠️  name が未設定です")
            valid = False
        if not current:
            print("  ⚠️  current が未設定です")
            valid = False
        if not target:
            print("  ⚠️  target が未設定です")
            valid = False

        # バージョン形式チェック
        if current and not any(c.isdigit() for c in current):
            print(f"  ⚠️  current のバージョン形式が不正: {current}")
            valid = False
        if target and not any(c.isdigit() for c in target):
            print(f"  ⚠️  target のバージョン形式が不正: {target}")
            valid = False

        # ソース検証
        valid_sources = ["github", "php.watch", "local"]
        for src in sources:
            if src not in valid_sources:
                print(f"  ⚠️  未知のソース: {src}")
                print(f"     有効なソース: {valid_sources}")
                valid = False

    return valid


def main():
    config_path = Path(__file__).parent / "config.toml"

    print("=" * 60)
    print("工程 1: 設定検証")
    print("=" * 60)

    if validate_config(config_path):
        print("\n" + "=" * 60)
        print("✅ 設定は有効です")
        print("=" * 60)
        print("\n次のステップ:")
        print("  cd ../2_fetch && uv run python run.py")
        return 0
    else:
        print("\n" + "=" * 60)
        print("❌ 設定にエラーがあります")
        print("=" * 60)
        print("\nconfig.toml を修正してから再実行してください。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
