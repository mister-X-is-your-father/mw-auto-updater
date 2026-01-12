#!/usr/bin/env python3
"""
工程 2: 変更情報の取得 (Fetch)

設定ファイルに基づき、ミドルウェアのバージョンアップに伴う変更情報を
複数ソースから取得し、構造化されたデータとして出力する。
"""

import argparse
import json
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Python 3.11+ has tomllib built-in
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        print("Error: tomli が必要です。`uv add tomli` を実行してください。")
        sys.exit(1)


# =============================================================================
# Version Utilities
# =============================================================================

def parse_version(version: str) -> tuple[int, ...]:
    """Parse version string to tuple of integers."""
    version = version.lstrip("^")
    parts = re.findall(r"\d+", version)
    return tuple(int(p) for p in parts)


def get_target_versions(current: str, target: str) -> list[str]:
    """Get list of versions between current and target."""
    c_major, c_minor = parse_version(current)[:2]
    t_major, t_minor = parse_version(target)[:2]

    versions = []
    for minor in range(c_minor + 1, t_minor + 1):
        versions.append(f"{c_major}.{minor}")

    return versions


# =============================================================================
# Source: GitHub (php/php-src UPGRADING)
# =============================================================================

def fetch_github_upgrading(version: str) -> list[dict[str, Any]]:
    """Fetch and parse UPGRADING file from GitHub php-src."""
    branch = f"PHP-{version}"
    url = f"https://raw.githubusercontent.com/php/php-src/{branch}/UPGRADING"

    changes = []

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "mw-upgrade-check/1.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            content = response.read().decode("utf-8")
            changes = parse_upgrading_content(content, version, url)

    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"  [github] Branch {branch} not found, trying master...", file=sys.stderr)
            try:
                url = "https://raw.githubusercontent.com/php/php-src/master/UPGRADING"
                req = urllib.request.Request(url, headers={"User-Agent": "mw-upgrade-check/1.0"})
                with urllib.request.urlopen(req, timeout=30) as response:
                    content = response.read().decode("utf-8")
                    changes = parse_upgrading_content(content, version, url)
            except urllib.error.URLError as e2:
                print(f"  [github] Error: {e2}", file=sys.stderr)
        else:
            print(f"  [github] HTTP Error: {e}", file=sys.stderr)
    except urllib.error.URLError as e:
        print(f"  [github] Error: {e}", file=sys.stderr)

    return changes


def parse_upgrading_content(content: str, version: str, url: str) -> list[dict[str, Any]]:
    """Parse UPGRADING markdown content into structured changes."""
    changes = []
    current_section = None
    current_subsection = None

    section_types = {
        "backward incompatible": "breaking",
        "deprecated": "deprecation",
        "removed": "removed",
        "new feature": "new",
        "new function": "new",
        "new class": "new",
        "changed function": "breaking",
    }

    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        section_match = re.match(r"^\d+\.\s*(.+)$", line)
        if section_match:
            section_name = section_match.group(1).lower()
            current_section = None
            for key, change_type in section_types.items():
                if key in section_name:
                    current_section = change_type
                    break
            i += 1
            continue

        if line.startswith("- ") and line.endswith(":"):
            current_subsection = line[2:-1]
            i += 1
            continue

        if current_section and line.startswith("- "):
            description = line[2:].strip()

            while i + 1 < len(lines) and lines[i + 1].startswith("  "):
                i += 1
                description += " " + lines[i].strip()

            if len(description) > 10:
                change = {
                    "version": version,
                    "type": current_section,
                    "description": description,
                    "source": "github",
                    "source_url": url,
                }
                if current_subsection:
                    change["category"] = current_subsection.lower()
                changes.append(change)

        i += 1

    return changes


# =============================================================================
# Source: php.watch
# =============================================================================

def fetch_phpwatch(version: str) -> list[dict[str, Any]]:
    """Fetch PHP changes from php.watch."""
    url = f"https://php.watch/versions/{version}"
    changes = []

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "mw-upgrade-check/1.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            html = response.read().decode("utf-8")

            # Extract deprecations
            deprecation_section = re.search(
                r"Deprecated.*?(?=<h[23]|$)", html, re.DOTALL | re.IGNORECASE
            )
            if deprecation_section:
                items = re.findall(r"<li[^>]*>([^<]+(?:<[^>]+>[^<]*)*)</li>", deprecation_section.group())
                for item in items[:20]:
                    clean = re.sub(r"<[^>]+>", "", item).strip()
                    if len(clean) > 10 and len(clean) < 300:
                        changes.append({
                            "version": version,
                            "type": "deprecation",
                            "description": clean,
                            "source": "php.watch",
                            "source_url": url,
                        })

            # Extract breaking changes
            breaking_section = re.search(
                r"Backward.?Incompatible.*?(?=<h[23]|$)", html, re.DOTALL | re.IGNORECASE
            )
            if breaking_section:
                items = re.findall(r"<li[^>]*>([^<]+(?:<[^>]+>[^<]*)*)</li>", breaking_section.group())
                for item in items[:20]:
                    clean = re.sub(r"<[^>]+>", "", item).strip()
                    if len(clean) > 10 and len(clean) < 300:
                        changes.append({
                            "version": version,
                            "type": "breaking",
                            "description": clean,
                            "source": "php.watch",
                            "source_url": url,
                        })

    except urllib.error.URLError as e:
        print(f"  [php.watch] Error fetching {url}: {e}", file=sys.stderr)

    return changes


# =============================================================================
# Source: Local TOML
# =============================================================================

def load_local_toml(version: str, data_dir: Path) -> list[dict[str, Any]]:
    """Load changes from local TOML file."""
    file_path = data_dir / f"php-{version}-changes.toml"
    if not file_path.exists():
        print(f"  [local] File not found: {file_path}", file=sys.stderr)
        return []

    print(f"  [local] Loading {file_path.name}", file=sys.stderr)

    with open(file_path, "rb") as f:
        data = tomllib.load(f)
        changes = data.get("changes", [])
        for change in changes:
            change["version"] = version
            change["source"] = "local"
            change["source_file"] = str(file_path.name)
        return changes


# =============================================================================
# Fetch Logic
# =============================================================================

def fetch_changes_by_source(
    source: str,
    versions: list[str],
    data_dir: Path
) -> dict[str, Any]:
    """Fetch changes from a specific source for all versions."""
    all_changes = []

    for version in versions:
        print(f"  Fetching {source} for version {version}...", file=sys.stderr)
        if source == "github":
            changes = fetch_github_upgrading(version)
        elif source == "php.watch":
            changes = fetch_phpwatch(version)
        elif source == "local":
            changes = load_local_toml(version, data_dir)
        else:
            print(f"  Unknown source: {source}", file=sys.stderr)
            changes = []

        all_changes.extend(changes)
        print(f"    Found {len(changes)} changes", file=sys.stderr)

    # Categorize
    breaking = [c for c in all_changes if c.get("type") == "breaking"]
    deprecations = [c for c in all_changes if c.get("type") == "deprecation"]
    removed = [c for c in all_changes if c.get("type") == "removed"]
    new_features = [c for c in all_changes if c.get("type") == "new"]

    return {
        "source": source,
        "summary": {
            "total": len(all_changes),
            "breaking": len(breaking),
            "deprecations": len(deprecations),
            "removed": len(removed),
            "new_features": len(new_features),
        },
        "breaking_changes": breaking,
        "deprecations": deprecations,
        "removed": removed,
        "new_features": new_features,
    }


def fetch_php_changes(
    current: str,
    target: str,
    sources: list[str],
    data_dir: Path,
    use_web: bool = True
) -> dict[str, Any]:
    """Fetch PHP changes from multiple sources."""
    versions = get_target_versions(current, target)

    if not use_web:
        sources = [s for s in sources if s == "local"]
        print(f"[--no-web] Using only local sources", file=sys.stderr)

    results_by_source = []
    for source in sources:
        print(f"\nFetching from {source}...", file=sys.stderr)
        result = fetch_changes_by_source(source, versions, data_dir)
        results_by_source.append(result)

    return {
        "middleware": "php",
        "current": current,
        "target": target.lstrip("^"),
        "versions_covered": versions,
        "sources": results_by_source,
    }


# =============================================================================
# Output Formatting
# =============================================================================

def format_markdown_output(result: dict[str, Any], timestamp: str) -> str:
    """Format results as human-readable markdown."""
    lines = []

    lines.append(f"# {result['middleware'].upper()} Upgrade Report")
    lines.append("")
    lines.append(f"- **Current Version**: {result['current']}")
    lines.append(f"- **Target Version**: {result['target']}")
    lines.append(f"- **Versions Covered**: {', '.join(result['versions_covered'])}")
    lines.append(f"- **Fetch Timestamp**: {timestamp}")
    lines.append("")

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| Source | Total | Breaking | Deprecations | Removed | New |")
    lines.append("|--------|-------|----------|--------------|---------|-----|")

    for source_result in result.get("sources", []):
        s = source_result["summary"]
        lines.append(f"| {source_result['source']} | {s['total']} | {s['breaking']} | {s['deprecations']} | {s['removed']} | {s['new_features']} |")

    lines.append("")

    # Details by source
    for source_result in result.get("sources", []):
        source_name = source_result["source"]

        if source_result["breaking_changes"]:
            lines.append(f"## Breaking Changes ({source_name})")
            lines.append("")
            for change in source_result["breaking_changes"]:
                lines.append(f"### [{change.get('version', '?')}] {change.get('category', 'general').title()}")
                lines.append("")
                lines.append(f"{change['description']}")
                if change.get("description_ja"):
                    lines.append(f"")
                    lines.append(f"> {change['description_ja']}")
                if change.get("pattern"):
                    lines.append(f"")
                    lines.append(f"**Pattern**: `{change['pattern']}`")
                if change.get("replacement"):
                    lines.append(f"")
                    lines.append(f"**Replacement**: {change['replacement']}")
                lines.append("")

        if source_result["deprecations"]:
            lines.append(f"## Deprecations ({source_name})")
            lines.append("")
            for change in source_result["deprecations"]:
                lines.append(f"### [{change.get('version', '?')}] {change.get('category', 'general').title()}")
                lines.append("")
                lines.append(f"{change['description']}")
                if change.get("description_ja"):
                    lines.append(f"")
                    lines.append(f"> {change['description_ja']}")
                if change.get("pattern"):
                    lines.append(f"")
                    lines.append(f"**Pattern**: `{change['pattern']}`")
                if change.get("replacement"):
                    lines.append(f"")
                    lines.append(f"**Replacement**: {change['replacement']}")
                lines.append("")

        if source_result["removed"]:
            lines.append(f"## Removed Features ({source_name})")
            lines.append("")
            for change in source_result["removed"]:
                lines.append(f"- [{change.get('version', '?')}] {change['description']}")
            lines.append("")

        if source_result["new_features"]:
            lines.append(f"## New Features ({source_name})")
            lines.append("")
            for change in source_result["new_features"]:
                lines.append(f"- [{change.get('version', '?')}] {change['description']}")
                if change.get("description_ja"):
                    lines.append(f"  > {change['description_ja']}")
            lines.append("")

    return "\n".join(lines)


# =============================================================================
# Main
# =============================================================================

def load_config(config_path: Path) -> dict[str, Any]:
    """Load TOML configuration file."""
    with open(config_path, "rb") as f:
        return tomllib.load(f)


def main():
    parser = argparse.ArgumentParser(
        description="工程 2: 変更情報の取得 (Fetch)"
    )
    parser.add_argument(
        "--config", "-c",
        default="../1_config/config.toml",
        help="Path to TOML config file (default: ../1_config/config.toml)"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="output",
        help="Output directory (default: output)"
    )
    parser.add_argument(
        "--no-web",
        action="store_true",
        help="Use only local data sources (no network requests)"
    )

    args = parser.parse_args()

    # Resolve paths
    script_dir = Path(__file__).parent.resolve()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = script_dir / config_path

    data_dir = script_dir / "data"
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = script_dir / output_dir

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Header
    print("=" * 60, file=sys.stderr)
    print("工程 2: 変更情報の取得 (Fetch)", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # Load config
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        print(f"\n先に工程1を実行してください:", file=sys.stderr)
        print(f"  cd ../1_config && uv run python run.py", file=sys.stderr)
        sys.exit(1)

    print(f"Config: {config_path}", file=sys.stderr)
    print(f"Data:   {data_dir}", file=sys.stderr)
    print(f"Output: {output_dir}", file=sys.stderr)

    config = load_config(config_path)

    # Timestamp for output files
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    # Process each middleware
    results = []
    output_files = []

    for mw in config.get("middleware", []):
        name = mw.get("name", "").lower()
        current = mw.get("current", "")
        target = mw.get("target", "")
        sources = mw.get("sources", ["local"])

        if isinstance(sources, str):
            sources = [sources]

        if not all([name, current, target]):
            print(f"Warning: Skipping incomplete middleware config: {mw}", file=sys.stderr)
            continue

        print(f"\n[{name.upper()}] {current} -> {target}", file=sys.stderr)

        if name == "php":
            result = fetch_php_changes(
                current,
                target,
                sources,
                data_dir,
                use_web=not args.no_web
            )
        else:
            print(f"Warning: Unsupported middleware: {name}", file=sys.stderr)
            continue

        # Add fetch timestamp
        fetch_timestamp = datetime.now(timezone.utc).isoformat()
        result["fetch_timestamp"] = fetch_timestamp

        results.append(result)

        # Write JSON output
        json_file = output_dir / f"changes-{name}-{timestamp}.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        output_files.append(json_file)
        print(f"\nJSON output: {json_file}", file=sys.stderr)

        # Write Markdown output
        md_file = output_dir / f"changes-{name}-{timestamp}.md"
        md_content = format_markdown_output(result, fetch_timestamp)
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(md_content)
        output_files.append(md_file)
        print(f"MD output:   {md_file}", file=sys.stderr)

    # Summary
    print("\n" + "=" * 60, file=sys.stderr)
    print("完了", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    if results:
        total_changes = sum(
            sum(s["summary"]["total"] for s in r.get("sources", []))
            for r in results
        )
        print(f"\n取得した変更: {total_changes} 件", file=sys.stderr)
        print(f"出力ファイル:", file=sys.stderr)
        for f in output_files:
            print(f"  - {f}", file=sys.stderr)

        print(f"\n次のステップ:", file=sys.stderr)
        print(f"  cd ../3_review && uv run python run.py", file=sys.stderr)
        return 0
    else:
        print("\nWarning: No middleware configurations processed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
