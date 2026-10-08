#!/bin/bash
# Add Spotify artists (a sources file made by spotify_artists.py), analyse the new songs, remove anything that is not a song.
#   nohup bash boost_artists.sh spotify_artists4.json > boost_artists4.log 2>&1 &
cd ~/groovyeverywhere || exit 1
SRC="${1:?usage: boost_artists.sh SOURCES.json}"
source ./env_keys.sh
while pgrep -f "[r]un_tests.py" > /dev/null || pgrep -f "[b]oost3\.sh" > /dev/null; do sleep 20; done
source .venv/bin/activate
python -u build_from_spotify.py --sources "$SRC" --no-named
echo "$(date) analysing the pool_youtube.csv songs still to do"
python -u run_tests.py --list pool_youtube.csv
echo "$(date) audio audit: removing anything that is not a song"
python -u audit_pool_audio.py --apply
echo "$(date) artists boost finished"
