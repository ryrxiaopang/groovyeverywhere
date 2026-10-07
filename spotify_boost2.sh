#!/bin/bash
# Eight more Spotify artists (spotify_artists2.json): their top 10 tracks (verified YouTube matches) + up to 8 more from their own
# YouTube channel, then analysis, then the audio audit.  Waits for any other analysis run first (one run at a time).
#   nohup bash spotify_boost2.sh > spotify_boost2.log 2>&1 &
cd ~/groovyeverywhere || exit 1
source ./env_keys.sh
while pgrep -f "[r]un_tests.py" > /dev/null || pgrep -f "[r]un_voice.py" > /dev/null || pgrep -f "[p]op_boost" > /dev/null || pgrep -f "[s]potify_boost" > /dev/null; do
    sleep 30
done
echo "$(date) matching the artists' songs on YouTube"
source .venv/bin/activate
python -u build_from_spotify.py --sources spotify_artists2.json --no-named
code=$?
if [ $code -ne 0 ]; then echo "$(date) !! build_from_spotify.py ended with an error (exit code $code)"; fi
echo "$(date) analysing the pool_youtube.csv songs still to do"
python -u run_tests.py --list pool_youtube.csv
echo "$(date) audio audit: removing anything that is not a song"
python -u audit_pool_audio.py --apply
echo "$(date) spotify boost 2 finished"
