#!/bin/bash

JOB_NAME=${1}
PATTERN=${2}
NOCOV=${3}

if scripts/needs_testrun.py -v "$JOB_NAME"
then
    # Sort the hashes to ensure a consistent ordering/division between each node
    riot list --hash-only "${PATTERN}" | sort | circleci tests split | xargs -n 1 -I {} riot -v run --exitfirst --pass-env -s {} $([[ ${NOCOV} == false ]] && echo '--no-cov' )
    ./scripts/check-diff ".riot/requirements/" "Changes detected after running riot. Consider deleting changed files, running scripts/compile-and-prune-test-requirements and committing the result."
else
    echo "No changes detected, skipping test run."
fi
