#!/bin/bash
#
# PHP Upgrade Check - PHPバージョンアップグレード変更点チェッカー
#
# Usage:
#   ./php-upgrade-check.sh --from=8.2 --to=8.5
#   ./php-upgrade-check.sh 8.2 8.5
#
# Output: JSON format with all breaking changes, deprecations between versions
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${SCRIPT_DIR}/data"

# Available PHP versions (in order)
VERSIONS=("8.2" "8.3" "8.4" "8.5")

# Parse arguments
FROM_VERSION=""
TO_VERSION=""
SHOW_HELP=false
FILTER_TYPE=""  # deprecation, breaking, removed, new

while [[ $# -gt 0 ]]; do
    case $1 in
        --from=*)
            FROM_VERSION="${1#*=}"
            shift
            ;;
        --to=*)
            TO_VERSION="${1#*=}"
            shift
            ;;
        --type=*)
            FILTER_TYPE="${1#*=}"
            shift
            ;;
        --help|-h)
            SHOW_HELP=true
            shift
            ;;
        *)
            # Positional arguments
            if [[ -z "$FROM_VERSION" ]]; then
                FROM_VERSION="$1"
            elif [[ -z "$TO_VERSION" ]]; then
                TO_VERSION="$1"
            fi
            shift
            ;;
    esac
done

# Show help
if [[ "$SHOW_HELP" == true ]] || [[ -z "$FROM_VERSION" ]] || [[ -z "$TO_VERSION" ]]; then
    cat << 'EOF'
PHP Upgrade Check - PHPバージョンアップグレード変更点チェッカー

Usage:
  ./php-upgrade-check.sh --from=8.2 --to=8.5
  ./php-upgrade-check.sh 8.2 8.5

Options:
  --from=VERSION    Source PHP version (e.g., 8.2)
  --to=VERSION      Target PHP version (e.g., 8.5)
  --type=TYPE       Filter by type: deprecation, breaking, removed, new
  --help, -h        Show this help message

Output:
  JSON format containing all changes between the specified versions.
  Each change includes:
    - version: PHP version where the change was introduced
    - type: deprecation | breaking | removed | new
    - category: syntax | function | class | ini | method | constant | attribute
    - description: English description
    - description_ja: Japanese description
    - pattern: grep-compatible regex pattern (for searching in codebase)
    - replacement: Recommended replacement or action

Examples:
  # Get all changes from PHP 8.2 to 8.5
  ./php-upgrade-check.sh 8.2 8.5

  # Get only deprecations
  ./php-upgrade-check.sh --from=8.2 --to=8.5 --type=deprecation

  # Use with grep to find affected code
  ./php-upgrade-check.sh 8.2 8.5 | jq -r '.changes[].pattern | select(. != null)' | while read p; do
    grep -rn "$p" ./src/ 2>/dev/null || true
  done
EOF
    exit 0
fi

# Validate versions exist
validate_version() {
    local version="$1"
    for v in "${VERSIONS[@]}"; do
        if [[ "$v" == "$version" ]]; then
            return 0
        fi
    done
    echo "Error: Unknown PHP version: $version" >&2
    echo "Available versions: ${VERSIONS[*]}" >&2
    exit 1
}

validate_version "$FROM_VERSION"
validate_version "$TO_VERSION"

# Get version index
get_version_index() {
    local version="$1"
    for i in "${!VERSIONS[@]}"; do
        if [[ "${VERSIONS[$i]}" == "$version" ]]; then
            echo "$i"
            return
        fi
    done
}

FROM_INDEX=$(get_version_index "$FROM_VERSION")
TO_INDEX=$(get_version_index "$TO_VERSION")

if [[ "$FROM_INDEX" -ge "$TO_INDEX" ]]; then
    echo "Error: --from version must be less than --to version" >&2
    exit 1
fi

# Collect all changes between versions
collect_changes() {
    local changes="[]"

    for ((i = FROM_INDEX + 1; i <= TO_INDEX; i++)); do
        local version="${VERSIONS[$i]}"
        local file="${DATA_DIR}/php-${version}-changes.json"

        if [[ -f "$file" ]]; then
            # Extract changes from file and add to array
            local file_changes
            file_changes=$(jq -c '.changes' "$file")
            changes=$(echo "$changes" "$file_changes" | jq -s 'add')
        fi
    done

    # Apply type filter if specified
    if [[ -n "$FILTER_TYPE" ]]; then
        changes=$(echo "$changes" | jq --arg type "$FILTER_TYPE" '[.[] | select(.type == $type)]')
    fi

    echo "$changes"
}

# Build output JSON
build_output() {
    local changes
    changes=$(collect_changes)

    jq -n \
        --arg from "$FROM_VERSION" \
        --arg to "$TO_VERSION" \
        --argjson changes "$changes" \
        '{
            from: $from,
            to: $to,
            total_changes: ($changes | length),
            summary: {
                deprecations: ([$changes[] | select(.type == "deprecation")] | length),
                breaking: ([$changes[] | select(.type == "breaking")] | length),
                removed: ([$changes[] | select(.type == "removed")] | length),
                new_features: ([$changes[] | select(.type == "new")] | length)
            },
            changes: $changes
        }'
}

# Check for jq
if ! command -v jq &> /dev/null; then
    echo "Error: jq is required but not installed." >&2
    echo "Install with: sudo yum install jq  # or: sudo apt install jq" >&2
    exit 1
fi

# Main output
build_output
