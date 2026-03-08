#!/usr/bin/env bash
# scripts/format.sh - Format code with Black and isort
# Usage: ./scripts/format.sh [--fix] [--check] [--verbose] [--help]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

FIX=false
CHECK=false
VERBOSE=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --fix)
            FIX=true
            shift
            ;;
        --check)
            CHECK=true
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --help)
            cat << EOF
Usage: $(basename "$0") [OPTIONS]

Format code using ruff format and ruff import sorting.

OPTIONS:
    --fix       Apply formatting changes (default)
    --check     Check only, fail if changes needed
    --verbose   Show detailed output
    --help      Display this help message

EXIT CODES:
    0           Code is properly formatted
    1           Formatting issues found
    2           Error running checks

EXAMPLES:
    $(basename "$0") --fix         # Apply formatting
    $(basename "$0") --check       # Check only
    $(basename "$0") --verbose     # Show detailed output
EOF
            exit 0
            ;;
        *)
            echo "Error: Unknown option: $1" >&2
            exit 2
            ;;
    esac
done

cd "$PROJECT_ROOT"

# Set verbosity
if $VERBOSE; then
    set -x
fi

echo "=== Formatting (ruff) ==="

# Determine mode
if $CHECK; then
    MODE="--check"
else
    MODE=""
fi

# Fix import sorting (ruff lint --select I)
if $CHECK; then
    if $VERBOSE; then
        echo "Checking import sorting..."
    fi
    ruff check --select I . || { echo "✗ Import sorting check failed" >&2; exit 1; }
else
    if $VERBOSE; then
        echo "Fixing import sorting..."
    fi
    ruff check --select I --fix . || { echo "✗ Import sorting fix failed" >&2; exit 1; }
fi

# Run ruff format
if $VERBOSE; then
    echo "Running ruff format..."
fi
ruff format $MODE . || { echo "✗ ruff format failed" >&2; exit 1; }

if [ -n "$MODE" ]; then
    echo "✓ Code formatting check passed"
else
    echo "✓ Code formatted successfully"
fi
exit 0
