#!/bin/bash
# Pool growth with MORE VARIETY inside the EXISTING genres (no new genres). Safe to re-run any time.
#   nohup bash grow_pool_overnight.sh [HH:MM] > grow_pool_overnight.log 2>&1 &
# Optional HH:MM (24 h, this computer's clock): do not start before that time (YouTube's daily search quota resets at
# midnight Pacific time = 15:00 in UTC+8).
# 1. loads the API keys (a non-interactive bash has none) and stops at once if one is missing;
# 2. waits until every other analysis run has finished (rule: one run at a time);
# 3. build_youtube.py --variety: saves after EVERY search, remembers finished searches, stops cleanly on the quota;
# 4. analyses the new songs. Each step's failure is written to the log, with the exit code, and stops the script.
cd ~/groovyeverywhere || exit 1
source ./env_keys.sh
need_keys YOUTUBE_API_KEY
if [ -n "$1" ]; then
    target=$(date -d "today $1" +%s)
    [ "$target" -lt "$(date +%s)" ] && target=$(date -d "tomorrow $1" +%s)
    echo "$(date) waiting until $1 (quota reset)"
    while [ "$(date +%s)" -lt "$target" ]; do sleep 60; done
fi
while pgrep -f "[r]un_tests.py" > /dev/null || pgrep -f "[r]un_voice.py" > /dev/null; do
    sleep 60
done
echo "$(date) other runs finished: building the list"
source .venv/bin/activate
python -u build_youtube.py --variety --per 10 --pages 1
code=$?
if [ $code -ne 0 ]; then echo "$(date) !! build_youtube.py ended with an error (exit code $code); what it found is saved"; fi
while pgrep -f "[r]un_tests.py" > /dev/null || pgrep -f "[r]un_voice.py" > /dev/null; do    # re-check: one run at a time
    sleep 60
done
echo "$(date) analysing the pool_youtube.csv songs still to do"
python -u run_tests.py --list pool_youtube.csv
code=$?
if [ $code -ne 0 ]; then echo "$(date) !! run_tests.py ended with an error (exit code $code)"; exit $code; fi
echo "$(date) pool growth finished"
