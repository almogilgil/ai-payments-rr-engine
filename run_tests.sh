#!/bin/bash
# Run the full test suite locally.
# Usage: ./run_tests.sh [pytest args]
# Examples:
#   ./run_tests.sh                        # run all tests
#   ./run_tests.sh -k test_calc           # run only calc tests
#   ./run_tests.sh --tb=short -q          # quiet mode

PYTHON=/Users/gil.almog/anaconda3/bin/python3.11

cd "$(dirname "$0")"
$PYTHON -m pytest tests/ -v "$@"
