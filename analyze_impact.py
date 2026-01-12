#!/usr/bin/env python3
"""
Impact Analyzer - コードベース影響分析ツール

破壊的変更が自社コードベースにどう影響するかを分析し、レポートを生成します。

Usage:
    # Claude API を使用
    uv run python analyze_impact.py --codebase /path/to/project --ai api

    # Claude Code 用のプロンプトを出力
    uv run python analyze_impact.py --codebase /path/to/project --ai claude-code

    # 変更リストを指定
    uv run python analyze_impact.py --changes changes.json --codebase /path/to/project
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Optional: anthropic SDK
try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


@dataclass
class CodeMatch:
    """A code match found in the codebase."""
    file_path: str
    line_number: int
    line_content: str
    context_before: list[str] = field(default_factory=list)
    context_after: list[str] = field(default_factory=list)


@dataclass
class ImpactResult:
    """Analysis result for a single breaking change."""
    change: dict[str, Any]
    matches: list[CodeMatch]
    ai_analysis: str = ""
    affected_files: list[str] = field(default_factory=list)


def search_codebase(
    codebase_path: Path,
    pattern: str,
    context_lines: int = 5
) -> list[CodeMatch]:
    """Search codebase for pattern matches using grep."""
    matches = []

    if not pattern:
        return matches

    try:
        # Use grep to find matches
        result = subprocess.run(
            [
                "grep", "-rn", "-E",
                "--include=*.php",
                "--include=*.js",
                "--include=*.ts",
                "--include=*.py",
                "--include=*.java",
                pattern,
                str(codebase_path)
            ],
            capture_output=True,
            text=True,
            timeout=60
        )

        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            # Parse grep output: file:line:content
            parts = line.split(":", 2)
            if len(parts) >= 3:
                file_path = parts[0]
                try:
                    line_number = int(parts[1])
                except ValueError:
                    continue
                line_content = parts[2] if len(parts) > 2 else ""

                # Get context
                context_before, context_after = get_context(
                    file_path, line_number, context_lines
                )

                matches.append(CodeMatch(
                    file_path=file_path,
                    line_number=line_number,
                    line_content=line_content.strip(),
                    context_before=context_before,
                    context_after=context_after
                ))

    except subprocess.TimeoutExpired:
        print(f"  Warning: Search timed out for pattern: {pattern}", file=sys.stderr)
    except Exception as e:
        print(f"  Warning: Search error: {e}", file=sys.stderr)

    return matches


def get_context(file_path: str, line_number: int, context_lines: int) -> tuple[list[str], list[str]]:
    """Get lines before and after the match."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        start = max(0, line_number - context_lines - 1)
        end = min(len(lines), line_number + context_lines)

        before = [l.rstrip() for l in lines[start:line_number - 1]]
        after = [l.rstrip() for l in lines[line_number:end]]

        return before, after
    except Exception:
        return [], []


def analyze_with_claude_api(
    change: dict[str, Any],
    matches: list[CodeMatch],
    api_key: str
) -> str:
    """Analyze impact using Claude API."""
    if not HAS_ANTHROPIC:
        return "Error: anthropic SDK not installed. Run: uv add anthropic"

    if not matches:
        return "該当するコードは見つかりませんでした。"

    # Build context for AI
    code_context = []
    for match in matches[:10]:  # Limit to 10 matches
        context = "\n".join([
            f"File: {match.file_path}:{match.line_number}",
            "```",
            *match.context_before[-3:],
            f">>> {match.line_content}  # Line {match.line_number}",
            *match.context_after[:3],
            "```",
            ""
        ])
        code_context.append(context)

    prompt = f"""あなたはPHPコードの専門家です。以下の破壊的変更が、提示されたコードにどのような影響を与えるか分析してください。

## 破壊的変更
- **説明**: {change.get('description', 'N/A')}
- **日本語説明**: {change.get('description_ja', 'N/A')}
- **推奨対応**: {change.get('replacement', 'N/A')}

## 該当コード
{chr(10).join(code_context)}

## 分析してください
1. **影響の概要**: この変更がコードにどう影響するか
2. **リスクレベル**: 高/中/低
3. **修正方法**: 具体的な修正コード例
4. **注意点**: 修正時の注意事項

簡潔かつ具体的に回答してください。"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
    except Exception as e:
        return f"API Error: {e}"


def generate_claude_code_prompt(
    change: dict[str, Any],
    matches: list[CodeMatch]
) -> str:
    """Generate a prompt for Claude Code to analyze."""
    if not matches:
        return "該当するコードは見つかりませんでした。"

    # Build file list
    files = list(set(m.file_path for m in matches))

    prompt_lines = [
        "## 分析タスク",
        "",
        f"以下のファイルを読んで、破壊的変更の影響を分析してください：",
        "",
        "### 破壊的変更",
        f"- **説明**: {change.get('description', 'N/A')}",
        f"- **日本語説明**: {change.get('description_ja', 'N/A')}",
        f"- **推奨対応**: {change.get('replacement', 'N/A')}",
        "",
        "### 該当ファイル",
    ]

    for match in matches[:10]:
        prompt_lines.append(f"- `{match.file_path}:{match.line_number}`")

    prompt_lines.extend([
        "",
        "### 分析項目",
        "1. 影響の概要",
        "2. リスクレベル（高/中/低）",
        "3. 具体的な修正コード",
        "4. 注意点",
    ])

    return "\n".join(prompt_lines)


def generate_markdown_report(
    results: list[ImpactResult],
    codebase_path: str,
    output_path: Path
) -> None:
    """Generate a Markdown impact report."""
    lines = [
        "# コードベース影響分析レポート",
        "",
        f"**生成日時**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**対象コードベース**: `{codebase_path}`",
        f"**分析した破壊的変更数**: {len(results)}",
        "",
        "---",
        "",
        "## サマリー",
        "",
        "| # | 変更内容 | 該当ファイル数 | リスク |",
        "|---|----------|---------------|--------|",
    ]

    for i, result in enumerate(results, 1):
        desc = result.change.get('description', 'N/A')[:50]
        file_count = len(set(m.file_path for m in result.matches))
        risk = "⚠️" if file_count > 0 else "✅"
        lines.append(f"| {i} | {desc}... | {file_count} | {risk} |")

    lines.extend(["", "---", ""])

    # Detailed results
    for i, result in enumerate(results, 1):
        change = result.change
        lines.extend([
            f"## {i}. {change.get('description', 'N/A')[:80]}",
            "",
            f"**バージョン**: {change.get('version', 'N/A')}",
            f"**カテゴリ**: {change.get('category', 'N/A')}",
            f"**日本語説明**: {change.get('description_ja', 'N/A')}",
            f"**推奨対応**: {change.get('replacement', 'N/A')}",
            "",
        ])

        if result.matches:
            lines.append("### 該当箇所")
            lines.append("")

            # Group by file
            files_matches: dict[str, list[CodeMatch]] = {}
            for match in result.matches:
                if match.file_path not in files_matches:
                    files_matches[match.file_path] = []
                files_matches[match.file_path].append(match)

            for file_path, file_matches in files_matches.items():
                lines.append(f"#### `{file_path}`")
                lines.append("")

                for match in file_matches[:5]:  # Limit per file
                    lines.append(f"**Line {match.line_number}**:")
                    lines.append("```php")
                    for ctx in match.context_before[-2:]:
                        lines.append(ctx)
                    lines.append(f">>> {match.line_content}  // ← 該当行")
                    for ctx in match.context_after[:2]:
                        lines.append(ctx)
                    lines.append("```")
                    lines.append("")

        if result.ai_analysis:
            lines.extend([
                "### AI 分析",
                "",
                result.ai_analysis,
                "",
            ])

        lines.extend(["---", ""])

    # Write report
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Report generated: {output_path}", file=sys.stderr)


def load_changes(changes_path: Path | None, data_dir: Path) -> list[dict[str, Any]]:
    """Load breaking changes from file or generate from local TOML."""
    if changes_path and changes_path.exists():
        with open(changes_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Extract breaking changes from multi-source format
            if isinstance(data, list) and data:
                all_breaking = []
                for mw_result in data:
                    for source in mw_result.get("sources", []):
                        all_breaking.extend(source.get("breaking_changes", []))
                        # Also include deprecations as they may be breaking
                        all_breaking.extend(source.get("deprecations", []))
                return all_breaking
            return data
    else:
        # Load from local TOML files
        changes = []
        for toml_file in data_dir.glob("*.toml"):
            try:
                import tomllib
            except ImportError:
                try:
                    import tomli as tomllib
                except ImportError:
                    continue

            with open(toml_file, "rb") as f:
                data = tomllib.load(f)
                for change in data.get("changes", []):
                    if change.get("type") in ["breaking", "deprecation"]:
                        change["version"] = data.get("version", "unknown")
                        changes.append(change)
        return changes


def main():
    parser = argparse.ArgumentParser(
        description="Impact Analyzer - コードベース影響分析ツール"
    )
    parser.add_argument(
        "--changes", "-c",
        type=Path,
        help="Path to breaking changes JSON file (from mw-upgrade-check)"
    )
    parser.add_argument(
        "--codebase", "-p",
        type=Path,
        required=True,
        help="Path to the target codebase to analyze"
    )
    parser.add_argument(
        "--ai",
        choices=["api", "claude-code", "none"],
        default="none",
        help="AI analysis mode: api (Claude API), claude-code (output prompts), none"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("impact_report.md"),
        help="Output report path (default: impact_report.md)"
    )
    parser.add_argument(
        "--api-key",
        help="Anthropic API key (or set ANTHROPIC_API_KEY env var)"
    )

    args = parser.parse_args()

    # Validate codebase path
    if not args.codebase.exists():
        print(f"Error: Codebase path not found: {args.codebase}", file=sys.stderr)
        sys.exit(1)

    # Get API key if needed
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if args.ai == "api" and not api_key:
        print("Error: API key required. Set --api-key or ANTHROPIC_API_KEY", file=sys.stderr)
        sys.exit(1)

    # Load breaking changes
    script_dir = Path(__file__).parent.resolve()
    data_dir = script_dir / "data"
    changes = load_changes(args.changes, data_dir)

    if not changes:
        print("No breaking changes found to analyze.", file=sys.stderr)
        sys.exit(0)

    print(f"Analyzing {len(changes)} breaking changes...", file=sys.stderr)

    # Analyze each change
    results: list[ImpactResult] = []

    for i, change in enumerate(changes, 1):
        pattern = change.get("pattern")
        desc = change.get("description", "Unknown")[:50]

        print(f"[{i}/{len(changes)}] {desc}...", file=sys.stderr)

        # Search codebase
        matches = search_codebase(args.codebase, pattern) if pattern else []
        print(f"  Found {len(matches)} matches", file=sys.stderr)

        # AI analysis
        ai_analysis = ""
        if matches:
            if args.ai == "api":
                print(f"  Analyzing with Claude API...", file=sys.stderr)
                ai_analysis = analyze_with_claude_api(change, matches, api_key)
            elif args.ai == "claude-code":
                ai_analysis = generate_claude_code_prompt(change, matches)

        results.append(ImpactResult(
            change=change,
            matches=matches,
            ai_analysis=ai_analysis,
            affected_files=list(set(m.file_path for m in matches))
        ))

    # Generate report
    generate_markdown_report(results, str(args.codebase), args.output)

    # Summary
    affected_count = sum(1 for r in results if r.matches)
    print(f"\nSummary:", file=sys.stderr)
    print(f"  Total changes analyzed: {len(results)}", file=sys.stderr)
    print(f"  Changes with affected code: {affected_count}", file=sys.stderr)
    print(f"  Report: {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
