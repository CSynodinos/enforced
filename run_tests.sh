#!/usr/bin/env bash

set -euo pipefail

run_simulation=false
run_unit_tests=true
only_failed=false

for arg in "$@"; do
	case "$arg" in
		--simulation)
			run_simulation=true
			;;
		--no-unit-tests)
			run_unit_tests=false
			;;
		--only-failed)
			only_failed=true
			;;
		-h|--help)
			echo "Usage: bash run_tests.sh [--simulation] [--no-unit-tests] [--only-failed]"
			exit 0
			;;
		*)
			echo "Unknown argument: $arg"
			echo "Usage: bash run_tests.sh [--simulation] [--no-unit-tests] [--only-failed]"
			exit 1
			;;
	esac
done

# "python -m pytest": the pytest of the interpreter that is active, not whichever one is first on PATH.
# No "if" around it: with set -e a failing test stops the script, and its exit status is pytest's.
if [[ "$run_unit_tests" == "true" ]]; then
	if [[ "$only_failed" == "true" ]]; then
		# Only what failed in the last run: no --cache-clear, which would forget it. With nothing
		# to run pytest exits with 5, which isn't a failure here; any other status stops the script.
		status=0
		python -m pytest -vv --log-cli-level=INFO --last-failed --last-failed-no-failures=none || status=$?
		if [[ "$status" -ne 0 && "$status" -ne 5 ]]; then
			exit "$status"
		fi
	else
		python -m pytest -vv --log-cli-level=INFO --cache-clear
	fi
fi

echo ""

sleep 3

if [[ "$run_simulation" == "true" ]]; then
	if [[ -f "tests/simulation.py" ]]; then
        echo "Running simulation tests..."
		python tests/simulation.py
	else
		echo "tests/simulation.py not found in project root"
		exit 1
	fi
fi
