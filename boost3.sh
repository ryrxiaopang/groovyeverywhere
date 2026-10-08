#!/bin/bash
# 8 Oct, round 3 of artist additions: two YouTube channels (whotfisarya, Dame Atlas) and 11 Spotify artists (spotify_artists3.json),
# then analysis and the audio audit.   nohup bash boost3.sh > boost3.log 2>&1 &
cd ~/groovyeverywhere || exit 1
source ./env_keys.sh
while pgrep -f "[r]un_tests.py" > /dev/null || pgrep -f "[a]dd_friend\.sh" > /dev/null; do sleep 20; done
source .venv/bin/activate
python -u add_channel.py https://www.youtube.com/channel/UCe2Pe7aji8CqU9aywcRWPBQ --artist whotfisarya --genre pop --max 20
python -u add_channel.py https://www.youtube.com/channel/UCDUkpN88t3Kfsix2zDRLYXg --artist "Dame Atlas" --genre rnb --max 25
python -u build_from_spotify.py --sources spotify_artists3.json --no-named
echo "$(date) analysing the pool_youtube.csv songs still to do"
python -u run_tests.py --list pool_youtube.csv
echo "$(date) audio audit: removing anything that is not a song"
python -u audit_pool_audio.py --apply
echo "$(date) boost 3 finished"
