# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PHP version upgrade checker that outputs breaking changes, deprecations, and new features between PHP versions. Designed for AI-assisted code migration workflows.

## Commands

```bash
# Check changes between PHP versions (outputs JSON)
./php-upgrade-check.sh 8.2 8.5
./php-upgrade-check.sh --from=8.2 --to=8.5

# Filter by change type
./php-upgrade-check.sh --from=8.2 --to=8.5 --type=deprecation

# Find affected code in a project
./php-upgrade-check.sh 8.2 8.5 | jq -r '.changes[].pattern | select(. != null)' | while read p; do
  grep -rn "$p" ./src/ 2>/dev/null || true
done
```

## Architecture

```
php-upgrade-check.sh     # Main CLI tool - merges version data and outputs JSON
data/
  php-8.3-changes.json   # Changes from 8.2→8.3
  php-8.4-changes.json   # Changes from 8.3→8.4
  php-8.5-changes.json   # Changes from 8.4→8.5
```

## Data Format

Each `data/php-X.X-changes.json` contains:
- `version`: Target PHP version
- `from`: Source PHP version
- `changes[]`: Array of change objects with:
  - `type`: `deprecation` | `breaking` | `removed` | `new`
  - `category`: `syntax` | `function` | `class` | `ini` | `method` | `constant` | `attribute`
  - `description` / `description_ja`: Change description
  - `pattern`: grep-compatible regex for finding affected code (null for new features)
  - `replacement`: Recommended fix or alternative

## Adding New PHP Versions

1. Create `data/php-X.Y-changes.json` following the existing format
2. Add the version to `VERSIONS` array in `php-upgrade-check.sh`

## Dependencies

- `jq` - Required for JSON processing
