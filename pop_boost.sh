#!/bin/bash
# Add Western pop / R&B / indie-pop songs (the pool's thinnest area: ~6% pop, ~4% soul/R&B) with yt-dlp searches (no API quota,
# well-played songs are fine), analyse them, then remove anything that is not a song (audit_pool_audio.py).
# Waits for any other analysis run first (one run at a time).      nohup bash pop_boost.sh > pop_boost.log 2>&1 &
cd ~/groovyeverywhere || exit 1
source ./env_keys.sh
while pgrep -f "[r]un_tests.py" > /dev/null || pgrep -f "[r]un_voice.py" > /dev/null || pgrep -f "[s]tyle_boost" > /dev/null || pgrep -f "[s]potify_boost" > /dev/null; do
    sleep 30
done
echo "$(date) searching with yt-dlp"
source .venv/bin/activate
python -u build_youtube.py --ytdlp --style pop --relevance --per 12 --max-views 50000000
code=$?
if [ $code -ne 0 ]; then echo "$(date) !! build_youtube.py ended with an error (exit code $code); what it found is saved"; fi
echo "$(date) analysing the pool_youtube.csv songs still to do"
python -u run_tests.py --list pool_youtube.csv
echo "$(date) audio audit: removing anything that is not a song"
python -u audit_pool_audio.py --apply
echo "$(date) pop boost finished"
