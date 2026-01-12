# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Middleware upgrade checker with stage-based workflow. Outputs breaking changes, deprecations, and new features between versions with human review checkpoints.

## Stage-Based Workflow

```
1_config/    →    2_fetch/    →    3_analyze/
(設定検証)        (変更取得)        (影響分析)
    ↓                ↓                 ↓
 config.toml    changes.json     impact_report.md
                 + review.md
```

Each stage requires manual execution (implicit human review between stages).

## Commands

```bash
# Stage 1: Validate configuration
cd 1_config && uv run python run.py

# Stage 2: Fetch breaking changes
cd 2_fetch && uv run python run.py
# Review output/changes-*.json and output/review-*.md before proceeding

# Stage 3: Analyze codebase impact
cd 3_analyze && uv run python run.py --codebase /path/to/project
cd 3_analyze && uv run python run.py --codebase /path/to/project --ai api  # With Claude API

# Legacy (direct version check)
./legacy/php-upgrade-check.sh 8.2 8.5
```

## Configuration

Edit `1_config/config.toml`:

```toml
[[middleware]]
name = "php"
current = "8.2"
target = "^8.5"    # ^8.5 = 8.5.x compatible
```

## Architecture

```
mw-auto-updater/
├── 1_config/              # Stage 1: Configuration
│   ├── config.toml        # Middleware versions to check
│   ├── run.py             # Config validation
│   └── README.md
├── 2_fetch/               # Stage 2: Fetch changes
│   ├── run.py             # Multi-source fetcher
│   ├── data/*.toml        # Local change definitions
│   └── output/            # JSON + Markdown for review
├── 3_analyze/             # Stage 3: Impact analysis
│   ├── run.py             # Codebase scanner + AI analysis
│   ├── input/             # Symlink or copy from 2_fetch/output
│   └── output/            # Impact report
├── legacy/                # Old shell scripts
└── docs/
    └── parallel-agent-strategy.md  # Parallel processing guide
```

## Supported Middleware

PHP, Laravel, Symfony, Node.js, Python, Django, Ruby, Rails, Go, Rust, Java, Kotlin, .NET, Vue.js, React

## Data Format

Each `2_fetch/data/php-X.X-changes.toml`:
- `version`: Target version
- `from`: Source version
- `[[changes]]`: Array with `type`, `category`, `description`, `pattern`, `replacement`

## Development Guidelines

See `docs/parallel-agent-strategy.md` for parallel agent processing rules when implementing features.
