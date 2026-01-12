#!/usr/bin/env python3
"""
Middleware Upgrade Checker
ミドルウェアアップグレード変更点チェッカー

Usage:
    uv run mw-upgrade-check [--config=config.toml] [--output=json|text]
"""

import argparse
import json
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

# Python 3.11+ has tomllib built-in, fallback for older versions
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None


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
    # Map version to branch name
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
            # Try master for unreleased versions
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

    # Section type mapping
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

        # Detect section headers (e.g., "1. Backward Incompatible Changes")
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

        # Detect subsection (e.g., "- Core:", "- PDO:")
        if line.startswith("- ") and line.endswith(":"):
            current_subsection = line[2:-1]
            i += 1
            continue

        # Detect list items with descriptions
        if current_section and line.startswith("- "):
            description = line[2:].strip()

            # Collect multi-line descriptions
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

            # Look for structured content
            # php.watch has sections like "Deprecated Features", "New Features", etc.

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
        return []

    if tomllib is None:
        # Fallback: simple TOML parser
        changes = []
        current_change = None

        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or not line:
                    continue
                if line == "[[changes]]":
                    if current_change:
                        current_change["version"] = version
                        current_change["source"] = "local"
                        changes.append(current_change)
                    current_change = {}
                elif "=" in line and current_change is not None:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    current_change[key] = value

        if current_change:
            current_change["version"] = version
            current_change["source"] = "local"
            changes.append(current_change)

        return changes

    with open(file_path, "rb") as f:
        data = tomllib.load(f)
        changes = data.get("changes", [])
        for change in changes:
            change["version"] = version
            change["source"] = "local"
        return changes


# =============================================================================
# Main Logic
# =============================================================================

def fetch_changes_by_source(
    source: str,
    versions: list[str],
    data_dir: Path
) -> dict[str, Any]:
    """Fetch changes from a specific source for all versions."""
    all_changes = []

    for version in versions:
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
        "all_changes": all_changes,
    }


def get_php_changes_multi_source(
    current: str,
    target: str,
    sources: list[str],
    data_dir: Path,
) -> dict[str, Any]:
    """Get PHP changes from multiple sources independently."""
    versions = get_target_versions(current, target)

    results_by_source = []
    for source in sources:
        print(f"Fetching from {source}...", file=sys.stderr)
        result = fetch_changes_by_source(source, versions, data_dir)
        results_by_source.append(result)

    return {
        "middleware": "php",
        "current": current,
        "target": target.lstrip("^"),
        "versions_covered": versions,
        "sources": results_by_source,
    }


def load_config(config_path: Path) -> dict[str, Any]:
    """Load TOML configuration file."""
    if tomllib is None:
        # Fallback: simple TOML parser
        config = {"middleware": []}
        current_mw = None

        with open(config_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or not line:
                    continue
                if line == "[[middleware]]":
                    current_mw = {"sources": ["local"]}  # default
                    config["middleware"].append(current_mw)
                elif "=" in line and current_mw is not None:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    # Handle array syntax
                    if value.startswith("[") and value.endswith("]"):
                        value = [v.strip().strip('"').strip("'")
                                for v in value[1:-1].split(",") if v.strip()]
                    else:
                        value = value.strip('"').strip("'")
                    current_mw[key] = value

        return config

    with open(config_path, "rb") as f:
        return tomllib.load(f)


def format_text_output(results: list[dict[str, Any]]) -> str:
    """Format results as human-readable text."""
    lines = []

    for result in results:
        lines.append(f"{'='*70}")
        lines.append(f"Middleware: {result['middleware'].upper()}")
        lines.append(f"Upgrade: {result['current']} → {result['target']}")
        lines.append(f"Versions: {', '.join(result['versions_covered'])}")
        lines.append(f"{'='*70}")

        for source_result in result.get("sources", []):
            source_name = source_result["source"]
            summary = source_result["summary"]

            lines.append(f"\n📦 Source: {source_name}")
            lines.append(f"   Total: {summary['total']} | "
                        f"Breaking: {summary['breaking']} | "
                        f"Deprecations: {summary['deprecations']} | "
                        f"Removed: {summary['removed']} | "
                        f"New: {summary['new_features']}")

            if source_result["breaking_changes"]:
                lines.append(f"\n   ⚠️  BREAKING CHANGES ({source_name}):")
                for change in source_result["breaking_changes"]:
                    desc = change['description'][:100] + "..." if len(change['description']) > 100 else change['description']
                    lines.append(f"      [{change.get('version', '?')}] {desc}")

            if source_result["deprecations"]:
                lines.append(f"\n   ⚡ DEPRECATIONS ({source_name}):")
                for change in source_result["deprecations"]:
                    desc = change['description'][:100] + "..." if len(change['description']) > 100 else change['description']
                    lines.append(f"      [{change.get('version', '?')}] {desc}")
                    if change.get("replacement"):
                        lines.append(f"         → {change['replacement']}")

        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Middleware Upgrade Checker - ミドルウェアアップグレード変更点チェッカー"
    )
    parser.add_argument(
        "--config", "-c",
        default="config.toml",
        help="Path to TOML config file (default: config.toml)"
    )
    parser.add_argument(
        "--output", "-o",
        choices=["json", "text"],
        default="json",
        help="Output format (default: json)"
    )

    args = parser.parse_args()

    # Resolve paths
    script_dir = Path(__file__).parent.resolve()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = script_dir / config_path

    data_dir = script_dir / "data"

    # Load config
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    config = load_config(config_path)

    # Process each middleware
    results = []

    for mw in config.get("middleware", []):
        name = mw.get("name", "").lower()
        current = mw.get("current", "")
        target = mw.get("target", "")
        sources = mw.get("sources", ["local"])

        # Ensure sources is a list
        if isinstance(sources, str):
            sources = [sources]

        if not all([name, current, target]):
            print(f"Warning: Skipping incomplete middleware config: {mw}", file=sys.stderr)
            continue

        if name == "php":
            result = get_php_changes_multi_source(
                current,
                target,
                sources,
                data_dir,
            )
            results.append(result)
        else:
            print(f"Warning: Unsupported middleware: {name}", file=sys.stderr)

    # Output results
    if args.output == "json":
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print(format_text_output(results))


if __name__ == "__main__":
    main()
