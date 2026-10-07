#!/bin/bash
# Source this at the top of any unattended script:  source ~/groovyeverywhere/env_keys.sh
# A non-interactive bash does NOT read ~/.bashrc, so JAMENDO_CLIENT_ID / YOUTUBE_API_KEY would be missing (this is what
# stopped the first overnight Voice run). This loads only those two lines from ~/.bashrc, never prints them, and stops
# the script at once if a needed key is still missing.
for name in JAMENDO_CLIENT_ID YOUTUBE_API_KEY AUDIUS_API_KEY; do
    if [ -z "${!name}" ]; then
        line=$(grep -E "^[[:space:]]*export[[:space:]]+${name}=" "$HOME/.bashrc" | tail -1)
        [ -n "$line" ] && eval "$line"
    fi
done
need_keys() {            # usage: need_keys JAMENDO_CLIENT_ID YOUTUBE_API_KEY
    for name in "$@"; do
        if [ -z "${!name}" ]; then
            echo "$(date) !! $name is not set (not in the environment and not exported in ~/.bashrc): stopping" >&2
            exit 3
        fi
    done
}
