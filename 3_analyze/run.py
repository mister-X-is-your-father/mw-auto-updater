#!/usr/bin/env python3
"""
工程 3: コードベース影響分析 (Analyze)

2_fetch で取得した変更情報を元に、対象コードベースへの影響を分析し、
該当箇所とコンテキストを含むレポートを生成する。
"""

import argparse
import glob as glob_module
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Optional: anthropic SDK
try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


# =============================================================================
# Configuration
# =============================================================================

# Middleware-specific file extensions for searching
MIDDLEWARE_FILE_EXTENSIONS: dict[str, list[str]] = {
    "php": ["php", "phtml", "inc"],
    "laravel": ["php", "blade.php", "phtml"],
    "python": ["py", "pyw"],
    "django": ["py", "html"],
    "node": ["js", "ts", "mjs", "cjs"],
    "react": ["js", "jsx", "ts", "tsx"],
    "vue": ["vue", "js", "ts"],
    "java": ["java"],
    "spring": ["java", "xml", "properties", "yml", "yaml"],
    "mysql": ["sql"],
    "postgresql": ["sql"],
    "ruby": ["rb", "erb"],
    "rails": ["rb", "erb", "html.erb"],
    "go": ["go"],
    # Default: search common code files
    "default": ["php", "js", "ts", "py", "java", "rb", "go", "rs", "sql"],
}

# Middleware display names for prompts
MIDDLEWARE_NAMES: dict[str, str] = {
    "php": "PHP",
    "laravel": "Laravel/PHP",
    "python": "Python",
    "django": "Django/Python",
    "node": "Node.js",
    "react": "React/JavaScript",
    "vue": "Vue.js",
    "java": "Java",
    "spring": "Spring/Java",
    "mysql": "MySQL",
    "postgresql": "PostgreSQL",
    "ruby": "Ruby",
    "rails": "Ruby on Rails",
    "go": "Go",
    "default": "ソフトウェア",
}

# File extension to code block language mapping
EXT_TO_LANGUAGE: dict[str, str] = {
    "php": "php",
    "phtml": "php",
    "inc": "php",
    "blade.php": "php",
    "py": "python",
    "pyw": "python",
    "js": "javascript",
    "mjs": "javascript",
    "cjs": "javascript",
    "ts": "typescript",
    "jsx": "jsx",
    "tsx": "tsx",
    "vue": "vue",
    "java": "java",
    "sql": "sql",
    "rb": "ruby",
    "erb": "erb",
    "go": "go",
    "rs": "rust",
    "xml": "xml",
    "yml": "yaml",
    "yaml": "yaml",
    "json": "json",
    "html": "html",
    "css": "css",
}


# =============================================================================
# Data Classes
# =============================================================================

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


# =============================================================================
# Utility Functions
# =============================================================================

def get_file_language(file_path: str) -> str:
    """Get code block language from file extension."""
    path = Path(file_path)
    name = path.name
    # Handle compound extensions like .blade.php
    for ext, lang in EXT_TO_LANGUAGE.items():
        if name.endswith(f".{ext}"):
            return lang
    # Fallback to simple extension
    ext = path.suffix.lstrip(".")
    return EXT_TO_LANGUAGE.get(ext, "")


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


# =============================================================================
# Search Functions
# =============================================================================

def search_codebase(
    codebase_path: Path,
    pattern: str,
    middleware: str = "default",
    context_lines: int = 5
) -> list[CodeMatch]:
    """Search codebase for pattern matches using grep."""
    matches = []

    if not pattern:
        return matches

    # Get file extensions for this middleware
    extensions = MIDDLEWARE_FILE_EXTENSIONS.get(
        middleware.lower(),
        MIDDLEWARE_FILE_EXTENSIONS["default"]
    )

    # Build grep command with middleware-specific extensions
    grep_cmd = ["grep", "-rn", "-E"]
    for ext in extensions:
        grep_cmd.append(f"--include=*.{ext}")
    grep_cmd.extend([pattern, str(codebase_path)])

    try:
        result = subprocess.run(
            grep_cmd,
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


# =============================================================================
# AI Analysis Functions
# =============================================================================

def analyze_with_claude_api(
    change: dict[str, Any],
    matches: list[CodeMatch],
    api_key: str,
    middleware: str = "default"
) -> str:
    """Analyze impact using Claude API."""
    if not HAS_ANTHROPIC:
        return "Error: anthropic SDK not installed. Run: uv add anthropic"

    if not matches:
        return "該当するコードは見つかりませんでした。"

    mw_name = MIDDLEWARE_NAMES.get(middleware.lower(), MIDDLEWARE_NAMES["default"])

    # Build context for AI
    code_context = []
    for match in matches[:10]:  # Limit to 10 matches
        lang = get_file_language(match.file_path)
        context = "\n".join([
            f"File: {match.file_path}:{match.line_number}",
            f"```{lang}",
            *match.context_before[-3:],
            f">>> {match.line_content}  # Line {match.line_number}",
            *match.context_after[:3],
            "```",
            ""
        ])
        code_context.append(context)

    prompt = f"""あなたは{mw_name}コードの専門家です。以下の破壊的変更が、提示されたコードにどのような影響を与えるか分析してください。

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

    prompt_lines = [
        "## 分析タスク",
        "",
        "以下のファイルを読んで、破壊的変更の影響を分析してください：",
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


# =============================================================================
# Input Loading
# =============================================================================

def load_changes_from_file(changes_path: Path) -> tuple[list[dict[str, Any]], str | None]:
    """Load changes from a single JSON file.

    Returns:
        tuple: (list of changes, middleware name or None)
    """
    with open(changes_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    middleware = data.get("middleware", None)

    # Handle 2_fetch output format
    if "sources" in data:
        all_changes = []
        for source in data.get("sources", []):
            all_changes.extend(source.get("breaking_changes", []))
            all_changes.extend(source.get("deprecations", []))
            all_changes.extend(source.get("removed", []))
        return all_changes, middleware

    # Handle simple list format
    if isinstance(data, list):
        return data, middleware

    # Handle legacy format
    return data.get("changes", []), middleware


def load_changes_from_input_dir(input_dir: Path) -> tuple[list[dict[str, Any]], str | None]:
    """Load changes from all JSON files in input directory.

    Returns:
        tuple: (list of changes, middleware name or None)
    """
    all_changes = []
    middleware = None

    json_files = sorted(input_dir.glob("*.json"))
    if not json_files:
        return [], None

    for json_file in json_files:
        print(f"  Loading: {json_file.name}", file=sys.stderr)
        changes, mw = load_changes_from_file(json_file)
        all_changes.extend(changes)
        if mw and not middleware:
            middleware = mw

    return all_changes, middleware


# =============================================================================
# Output Generation
# =============================================================================

def generate_json_output(
    results: list[ImpactResult],
    codebase_path: str,
    middleware: str,
    timestamp: str
) -> dict[str, Any]:
    """Generate structured JSON output."""
    output = {
        "analyze_timestamp": timestamp,
        "codebase": codebase_path,
        "middleware": middleware,
        "summary": {
            "total_changes": len(results),
            "changes_with_matches": sum(1 for r in results if r.matches),
            "total_affected_files": len(set(
                f for r in results for f in r.affected_files
            )),
            "total_matches": sum(len(r.matches) for r in results),
        },
        "results": []
    }

    for result in results:
        item = {
            "change": result.change,
            "affected_files": result.affected_files,
            "match_count": len(result.matches),
            "matches": [
                {
                    "file": m.file_path,
                    "line": m.line_number,
                    "content": m.line_content,
                    "context_before": m.context_before[-3:],
                    "context_after": m.context_after[:3],
                }
                for m in result.matches[:20]  # Limit matches per change
            ],
        }
        if result.ai_analysis:
            item["ai_analysis"] = result.ai_analysis
        output["results"].append(item)

    return output


def generate_markdown_report(
    results: list[ImpactResult],
    codebase_path: str,
    middleware: str,
    timestamp: str
) -> str:
    """Generate a Markdown impact report."""
    lines = [
        "# コードベース影響分析レポート",
        "",
        f"**生成日時**: {timestamp}",
        f"**対象コードベース**: `{codebase_path}`",
        f"**ミドルウェア**: {middleware}",
        f"**分析した変更数**: {len(results)}",
        "",
        "---",
        "",
        "## サマリー",
        "",
        "| # | 変更タイプ | 変更内容 | 該当ファイル数 | リスク |",
        "|---|-----------|----------|---------------|--------|",
    ]

    for i, result in enumerate(results, 1):
        change_type = result.change.get('type', 'unknown')
        desc = result.change.get('description', 'N/A')[:50]
        file_count = len(set(m.file_path for m in result.matches))
        risk = "⚠️ 要対応" if file_count > 0 else "✅ 影響なし"
        lines.append(f"| {i} | {change_type} | {desc}... | {file_count} | {risk} |")

    lines.extend(["", "---", ""])

    # Count changes with matches
    affected_results = [r for r in results if r.matches]
    if not affected_results:
        lines.extend([
            "## 結果",
            "",
            "**該当箇所なし** - コードベースにアップグレードによる影響はありませんでした。",
            "",
        ])
        return "\n".join(lines)

    # Detailed results (only for changes with matches)
    for i, result in enumerate(affected_results, 1):
        change = result.change
        lines.extend([
            f"## {i}. {change.get('description', 'N/A')[:80]}",
            "",
            f"- **バージョン**: {change.get('version', 'N/A')}",
            f"- **タイプ**: {change.get('type', 'N/A')}",
            f"- **カテゴリ**: {change.get('category', 'N/A')}",
        ])

        if change.get('description_ja'):
            lines.append(f"- **日本語説明**: {change.get('description_ja')}")
        if change.get('replacement'):
            lines.append(f"- **推奨対応**: {change.get('replacement')}")
        if change.get('pattern'):
            lines.append(f"- **検索パターン**: `{change.get('pattern')}`")

        lines.append("")

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

                lang = get_file_language(file_path)

                for match in file_matches[:5]:  # Limit per file
                    lines.append(f"**Line {match.line_number}**:")
                    lines.append(f"```{lang}")
                    for ctx in match.context_before[-2:]:
                        lines.append(ctx)
                    lines.append(f">>> {match.line_content}  // <-- 該当行")
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

    return "\n".join(lines)


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="工程 3: コードベース影響分析 (Analyze)"
    )
    parser.add_argument(
        "--codebase", "-p",
        type=Path,
        required=True,
        help="Path to the target codebase to analyze"
    )
    parser.add_argument(
        "--changes", "-c",
        type=Path,
        help="Path to changes JSON file (default: input/*.json)"
    )
    parser.add_argument(
        "--middleware", "-m",
        default="",
        help=f"Middleware type for file filtering. Available: {', '.join(MIDDLEWARE_FILE_EXTENSIONS.keys())}"
    )
    parser.add_argument(
        "--ai",
        choices=["api", "claude-code", "none"],
        default="none",
        help="AI analysis mode: api (Claude API), claude-code (output prompts), none"
    )
    parser.add_argument(
        "--api-key",
        help="Anthropic API key (or set ANTHROPIC_API_KEY env var)"
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=Path,
        default=Path("output"),
        help="Output directory (default: output)"
    )

    args = parser.parse_args()

    # Resolve paths
    script_dir = Path(__file__).parent.resolve()
    input_dir = script_dir / "input"
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = script_dir / output_dir

    # Header
    print("=" * 60, file=sys.stderr)
    print("工程 3: コードベース影響分析 (Analyze)", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # Validate codebase path
    if not args.codebase.exists():
        print(f"Error: Codebase path not found: {args.codebase}", file=sys.stderr)
        sys.exit(1)

    codebase_path = args.codebase.resolve()
    print(f"Codebase: {codebase_path}", file=sys.stderr)

    # Get API key if needed
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if args.ai == "api" and not api_key:
        print("Error: API key required. Set --api-key or ANTHROPIC_API_KEY", file=sys.stderr)
        sys.exit(1)

    # Load changes
    print(f"\nLoading changes...", file=sys.stderr)
    if args.changes:
        if not args.changes.exists():
            print(f"Error: Changes file not found: {args.changes}", file=sys.stderr)
            sys.exit(1)
        changes, detected_middleware = load_changes_from_file(args.changes)
        print(f"  Loaded from: {args.changes}", file=sys.stderr)
    else:
        if not input_dir.exists() or not list(input_dir.glob("*.json")):
            print(f"Error: No input files found in {input_dir}", file=sys.stderr)
            print(f"\n使用方法:", file=sys.stderr)
            print(f"  1. 2_fetch の出力を input/ にコピー:", file=sys.stderr)
            print(f"     cp ../2_fetch/output/changes-*.json input/", file=sys.stderr)
            print(f"  2. または --changes オプションで直接指定:", file=sys.stderr)
            print(f"     uv run python run.py --codebase /path/to/code --changes /path/to/changes.json", file=sys.stderr)
            sys.exit(1)
        changes, detected_middleware = load_changes_from_input_dir(input_dir)

    if not changes:
        print("No changes found to analyze.", file=sys.stderr)
        sys.exit(0)

    # Determine middleware type
    middleware = args.middleware or detected_middleware or "default"
    print(f"Middleware: {middleware}", file=sys.stderr)
    print(f"Total changes: {len(changes)}", file=sys.stderr)

    # Filter to only analyze changes with patterns
    analyzable_changes = [c for c in changes if c.get("pattern")]
    print(f"Changes with patterns: {len(analyzable_changes)}", file=sys.stderr)

    if not analyzable_changes:
        print("\nWarning: No changes have search patterns. Skipping analysis.", file=sys.stderr)
        analyzable_changes = changes  # Still include for reporting

    # Analyze each change
    print(f"\nAnalyzing codebase...", file=sys.stderr)
    results: list[ImpactResult] = []

    for i, change in enumerate(analyzable_changes, 1):
        pattern = change.get("pattern")
        desc = change.get("description", "Unknown")[:50]
        change_type = change.get("type", "unknown")

        print(f"[{i}/{len(analyzable_changes)}] [{change_type}] {desc}...", file=sys.stderr)

        # Search codebase
        matches = search_codebase(codebase_path, pattern, middleware) if pattern else []
        print(f"  Found {len(matches)} matches", file=sys.stderr)

        # AI analysis
        ai_analysis = ""
        if matches:
            if args.ai == "api":
                print(f"  Analyzing with Claude API...", file=sys.stderr)
                ai_analysis = analyze_with_claude_api(change, matches, api_key, middleware)
            elif args.ai == "claude-code":
                ai_analysis = generate_claude_code_prompt(change, matches)

        results.append(ImpactResult(
            change=change,
            matches=matches,
            ai_analysis=ai_analysis,
            affected_files=list(set(m.file_path for m in matches))
        ))

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate timestamp
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    timestamp_iso = datetime.now(timezone.utc).isoformat()

    # Write JSON output
    json_output = generate_json_output(results, str(codebase_path), middleware, timestamp_iso)
    json_file = output_dir / f"impact-{middleware}-{timestamp}.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(json_output, f, indent=2, ensure_ascii=False)

    # Write Markdown output
    md_content = generate_markdown_report(results, str(codebase_path), middleware, timestamp_iso)
    md_file = output_dir / "impact_report.md"
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(md_content)

    # Summary
    affected_count = sum(1 for r in results if r.matches)
    total_matches = sum(len(r.matches) for r in results)
    affected_files = len(set(f for r in results for f in r.affected_files))

    print("\n" + "=" * 60, file=sys.stderr)
    print("完了", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"\n分析結果:", file=sys.stderr)
    print(f"  分析した変更数: {len(results)}", file=sys.stderr)
    print(f"  影響のある変更: {affected_count}", file=sys.stderr)
    print(f"  該当箇所の総数: {total_matches}", file=sys.stderr)
    print(f"  影響を受けるファイル数: {affected_files}", file=sys.stderr)
    print(f"\n出力ファイル:", file=sys.stderr)
    print(f"  - {json_file}", file=sys.stderr)
    print(f"  - {md_file}", file=sys.stderr)

    if affected_count > 0:
        print(f"\n⚠️  {affected_count} 件の変更がコードベースに影響します。", file=sys.stderr)
        print(f"   詳細は {md_file} を確認してください。", file=sys.stderr)
    else:
        print(f"\n✅ コードベースへの影響はありませんでした。", file=sys.stderr)

    print(f"\n次のステップ:", file=sys.stderr)
    print(f"  cd ../4_fix && uv run python run.py", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
