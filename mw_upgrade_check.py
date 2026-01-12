#!/usr/bin/env python3
"""
Middleware Upgrade Checker
ミドルウェアアップグレード変更点チェッカー

Usage:
    ./mw-upgrade-check.py [--config=config.toml] [--output=json|text]
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
    # Remove ^ prefix if present
    version = version.lstrip("^")
    # Extract numeric parts
    parts = re.findall(r"\d+", version)
    return tuple(int(p) for p in parts)


def version_in_range(version: str, current: str, target: str) -> bool:
    """Check if version is between current and target."""
    v = parse_version(version)
    c = parse_version(current)
    t = parse_version(target)
    return c < v <= t


def get_target_versions(current: str, target: str) -> list[str]:
    """Get list of versions between current and target."""
    # For PHP, we support 8.2 -> 8.5
    c_major, c_minor = parse_version(current)[:2]
    t_major, t_minor = parse_version(target)[:2]

    versions = []
    for minor in range(c_minor + 1, t_minor + 1):
        versions.append(f"{c_major}.{minor}")

    return versions


def fetch_php_changes_from_web(version: str) -> list[dict[str, Any]]:
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
            deprecation_patterns = [
                (r"deprecated[:\s]+([^<\n]+)", "deprecation"),
                (r"breaking change[:\s]+([^<\n]+)", "breaking"),
                (r"removed[:\s]+([^<\n]+)", "removed"),
            ]

            for pattern, change_type in deprecation_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                for match in matches[:10]:  # Limit to prevent noise
                    clean_text = re.sub(r"<[^>]+>", "", match).strip()
                    if len(clean_text) > 10 and len(clean_text) < 200:
                        changes.append({
                            "version": version,
                            "type": change_type,
                            "description": clean_text,
                            "source": url
                        })

    except urllib.error.URLError as e:
        print(f"Warning: Could not fetch from {url}: {e}", file=sys.stderr)

    return changes


def load_local_changes(version: str, data_dir: Path) -> list[dict[str, Any]]:
    """Load changes from local TOML file."""
    file_path = data_dir / f"php-{version}-changes.toml"
    if not file_path.exists():
        return []

    if tomllib is None:
        # Fallback: simple TOML parser for changes
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
                        changes.append(current_change)
                    current_change = {}
                elif "=" in line and current_change is not None:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    current_change[key] = value

        if current_change:
            current_change["version"] = version
            changes.append(current_change)

        return changes

    with open(file_path, "rb") as f:
        data = tomllib.load(f)
        changes = data.get("changes", [])
        for change in changes:
            change["version"] = version
        return changes


def get_php_changes(
    current: str,
    target: str,
    data_dir: Path,
    use_web: bool = True
) -> dict[str, Any]:
    """Get all PHP changes between versions."""
    versions = get_target_versions(current, target)
    all_changes = []

    for version in versions:
        # Try local first
        local_changes = load_local_changes(version, data_dir)

        if local_changes:
            all_changes.extend(local_changes)
        elif use_web:
            # Fallback to web fetch
            web_changes = fetch_php_changes_from_web(version)
            all_changes.extend(web_changes)

    # Categorize changes
    breaking = [c for c in all_changes if c.get("type") == "breaking"]
    deprecations = [c for c in all_changes if c.get("type") == "deprecation"]
    removed = [c for c in all_changes if c.get("type") == "removed"]
    new_features = [c for c in all_changes if c.get("type") == "new"]

    return {
        "middleware": "php",
        "current": current,
        "target": target.lstrip("^"),
        "versions_covered": versions,
        "summary": {
            "total": len(all_changes),
            "breaking": len(breaking),
            "deprecations": len(deprecations),
            "removed": len(removed),
            "new_features": len(new_features)
        },
        "breaking_changes": breaking,
        "deprecations": deprecations,
        "removed": removed,
        "new_features": new_features,
        "all_changes": all_changes
    }


def load_config(config_path: Path) -> dict[str, Any]:
    """Load TOML configuration file."""
    if tomllib is None:
        # Fallback: simple TOML parser for basic structure
        config = {"middleware": []}
        current_mw = None

        with open(config_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or not line:
                    continue
                if line == "[[middleware]]":
                    current_mw = {}
                    config["middleware"].append(current_mw)
                elif "=" in line and current_mw is not None:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    current_mw[key] = value

        return config

    with open(config_path, "rb") as f:
        return tomllib.load(f)


def format_text_output(results: list[dict[str, Any]]) -> str:
    """Format results as human-readable text."""
    lines = []

    for result in results:
        lines.append(f"{'='*60}")
        lines.append(f"Middleware: {result['middleware'].upper()}")
        lines.append(f"Upgrade: {result['current']} → {result['target']}")
        lines.append(f"Versions: {', '.join(result['versions_covered'])}")
        lines.append(f"{'='*60}")

        summary = result["summary"]
        lines.append(f"\nSummary:")
        lines.append(f"  Total changes: {summary['total']}")
        lines.append(f"  Breaking:      {summary['breaking']}")
        lines.append(f"  Deprecations:  {summary['deprecations']}")
        lines.append(f"  Removed:       {summary['removed']}")
        lines.append(f"  New features:  {summary['new_features']}")

        if result["breaking_changes"]:
            lines.append(f"\n⚠️  BREAKING CHANGES:")
            for change in result["breaking_changes"]:
                lines.append(f"  [{change.get('version', '?')}] {change['description']}")
                if change.get("pattern"):
                    lines.append(f"       Pattern: {change['pattern']}")

        if result["deprecations"]:
            lines.append(f"\n⚡ DEPRECATIONS:")
            for change in result["deprecations"]:
                lines.append(f"  [{change.get('version', '?')}] {change['description']}")
                if change.get("replacement"):
                    lines.append(f"       → {change['replacement']}")

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
    parser.add_argument(
        "--no-web",
        action="store_true",
        help="Don't fetch from web, use local data only"
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

        if not all([name, current, target]):
            print(f"Warning: Skipping incomplete middleware config: {mw}", file=sys.stderr)
            continue

        if name == "php":
            result = get_php_changes(
                current,
                target,
                data_dir,
                use_web=not args.no_web
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
