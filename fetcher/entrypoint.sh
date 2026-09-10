#!/usr/bin/env bash
# Dispatches `docker compose run --rm fetcher <provider> [args...]` to the
# matching provider script, so none of vaneck.py/spdr.py/etc. need to change
# to be runnable in the container - only the routing lives here. Every
# argument after <provider> passes straight through to that script's own
# argparse (--output/--tickers/--limit/--delay, see fetcher/common.py).
set -euo pipefail

providers=(vaneck spdr ark ishares vanguard invesco)

provider="${1:-}"
if [[ -z "$provider" ]]; then
    echo "Usage: docker compose run --rm fetcher <provider> [--tickers ...] [--limit N] [--output FILE]" >&2
    echo "Providers: ${providers[*]}" >&2
    exit 1
fi
shift

match=0
for p in "${providers[@]}"; do
    if [[ "$p" == "$provider" ]]; then
        match=1
        break
    fi
done
if [[ "$match" -eq 0 ]]; then
    echo "Unknown provider '$provider'. Providers: ${providers[*]}" >&2
    exit 1
fi

# --output is repeated here (not just defaulted in the script) so a caller's
# own --output later in "$@" still wins - argparse keeps the last value for
# a repeated flag.
exec python "${provider}.py" --output "/output/${provider}_holdings.json" "$@"
