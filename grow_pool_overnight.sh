#!/bin/bash
# Overnight pool growth (7 Oct 2026): MORE VARIETY inside the EXISTING genres (no new genres).
# Waits until every other analysis run has finished (rule: one run at a time), searches 3 extra sub-style queries per
# genre (build_youtube.EXTRA_QUERIES, round by round so every genre is covered even if the YouTube quota runs out),
# then analyses the new songs. Resumable: run it again any time.
#   nohup bash grow_pool_overnight.sh > grow_pool_overnight.log 2>&1 &     (start it from `bash -ic`: needs YOUTUBE_API_KEY)
cd ~/groovyeverywhere || exit 1
while pgrep -f "[r]un_tests.py" > /dev/null || pgrep -f "[s]tart_voice_dev" > /dev/null || pgrep -f "[r]un_voice.py" > /dev/null; do
    sleep 60
done
echo "$(date) other runs finished: building the list"
source .venv/bin/activate
python -u build_youtube.py --variety --per 10 --pages 1
echo "$(date) analysing the pool_youtube.csv songs still to do"
python -u run_tests.py --list pool_youtube.csv
echo "$(date) pool growth finished"
