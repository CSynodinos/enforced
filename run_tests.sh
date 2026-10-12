#!/usr/bin/env bash

set -euo pipefail

run_simulation=false
run_unit_tests=true

for arg in "$@"; do
	case "$arg" in
		--simulation)
			run_simulation=true
			;;
		--no-unit-tests)
			run_unit_tests=false
			;;
		-h|--help)
			echo "Usage: bash run_tests.sh [--simulation] [--no-unit-tests]"
			exit 0
			;;
		*)
			echo "Unknown argument: $arg"
			echo "Usage: bash run_tests.sh [--simulation] [--no-unit-tests]"
			exit 1
			;;
	esac
done

# "python -m pytest": the pytest of the interpreter that is active, not whichever one is first on PATH.
# No "if" around it: with set -e a failing test stops the script, and its exit status is pytest's.
if [[ "$run_unit_tests" == "true" ]]; then
	python -m pytest -vv --log-cli-level=INFO --cache-clear
fi

if [[ "$run_simulation" == "true" ]]; then
	if [[ -f "tests/simulation.py" ]]; then
        echo "Running simulation tests..."
		python tests/simulation.py
	else
		echo "tests/simulation.py not found in project root"
		exit 1
	fi
fi
