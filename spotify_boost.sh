#!/bin/bash
# AFTER the Japanese-style run (style_boost.sh) and any other analysis has finished (one run at a time): find the songs of the
# Spotify playlists / artists and the named artists on YouTube (verified matches only), add them to pool_youtube.csv, analyse them.
#   nohup bash spotify_boost.sh > spotify_boost.log 2>&1 &
cd ~/groovyeverywhere || exit 1
source ./env_keys.sh
while pgrep -f "[r]un_tests.py" > /dev/null || pgrep -f "[r]un_voice.py" > /dev/null || pgrep -f "[s]tyle_boost" > /dev/null || pgrep -f "[a]nalyse_list_then_pool" > /dev/null; do
    sleep 30
done
echo "$(date) other runs finished: matching the Spotify songs on YouTube"
source .venv/bin/activate
python -u build_from_spotify.py
code=$?
if [ $code -ne 0 ]; then echo "$(date) !! build_from_spotify.py ended with an error (exit code $code)"; fi
echo "$(date) analysing the pool_youtube.csv songs still to do"
python -u run_tests.py --list pool_youtube.csv
echo "$(date) spotify boost finished (exit code $?)"
