# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Middleware upgrade checker that outputs breaking changes, deprecations, and new features between versions. Supports configuration-driven workflow with TOML and web-fetched changelogs.

## Commands

```bash
# Phase 1: Config-based check (reads config.toml)
uv run mw-upgrade-check                    # JSON output
uv run mw-upgrade-check --output=text      # Human-readable output

# Phase 2: Impact analysis
uv run python analyze_impact.py --codebase /path/to/project          # Basic analysis
uv run python analyze_impact.py --codebase /path/to/project --ai api # With Claude API
uv run python analyze_impact.py --codebase /path/to/project --ai claude-code # Claude Code prompts

# Legacy shell script
./php-upgrade-check.sh 8.2 8.5
```

## Configuration

Edit `config.toml` to specify middleware and versions:

```toml
[[middleware]]
name = "php"
current = "8.2"
target = "^8.5"    # ^8.5 = 8.5.x compatible
```

## Architecture

```
config.toml              # TOML configuration (middleware, versions)
mw_upgrade_check.py      # Phase 1: Change detection (multi-source)
analyze_impact.py        # Phase 2: Codebase impact analysis
php-upgrade-check.sh     # Legacy shell script
data/
  php-8.3-changes.toml   # Changes from 8.2→8.3
  php-8.4-changes.toml   # Changes from 8.3→8.4
  php-8.5-changes.toml   # Changes from 8.4→8.5
```

## Data Format

Each `data/php-X.X-changes.toml` contains:
- `version`: Target PHP version
- `from`: Source PHP version
- `[[changes]]`: Array of change objects with:
  - `type`: `deprecation` | `breaking` | `removed` | `new`
  - `category`: `syntax` | `function` | `class` | `ini` | `method` | `constant` | `attribute`
  - `description` / `description_ja`: Change description
  - `pattern`: grep-compatible regex for finding affected code (null for new features)
  - `replacement`: Recommended fix or alternative

## Adding New Middleware

1. Add handler function in `mw_upgrade_check.py` (e.g., `get_laravel_changes()`)
2. Register in the main processing loop
3. Optionally add local TOML data files in `data/`

## Dependencies

- Python 3.9+
- `jq` - For shell script JSON processing
