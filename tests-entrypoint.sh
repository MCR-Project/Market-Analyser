#!/usr/bin/env bash
# `docker compose run --rm tests [pytest args]` runs pytest - with no args,
# a -k/-x flag, or a bare path, since pytest.ini's testpaths already cover
# both trees so no path is required. `docker compose run --rm tests lint`
# runs the frontend's ESLint instead, since app/package.json's lint script
# only makes sense run from app/. `bash`/`sh` are an escape hatch to poke
# around in the image. Anything else defaults to pytest too, on the
# assumption that an unrecognized first word is a pytest arg (a test id, a
# marker expression, a plugin flag) rather than a command to exec - the
# opposite default would silently swallow a typo'd flag as "command not
# found" instead of running it as a test filter.
set -euo pipefail

if [[ $# -eq 0 ]]; then
    exec pytest
fi

case "$1" in
    lint)
        shift
        exec npm --prefix app run lint -- "$@"
        ;;
    bash|sh)
        exec "$@"
        ;;
    *)
        exec pytest "$@"
        ;;
esac
