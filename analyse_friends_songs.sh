#!/bin/bash
# Analyse the friends' songs (friends_songs.csv, YouTube; the audio is deleted after each song) once every other
# analysis run has finished (one run at a time).   nohup bash analyse_friends_songs.sh > analyse_friends_songs.log 2>&1 &
cd ~/groovyeverywhere || exit 1
source ./env_keys.sh
while pgrep -f "[r]un_tests.py" > /dev/null || pgrep -f "[r]un_voice.py" > /dev/null; do
    sleep 30
done
echo "$(date) analysing the friends' songs"
source .venv/bin/activate
python -u run_tests.py --list friends_songs.csv
code=$?
if [ $code -ne 0 ]; then echo "$(date) !! run_tests.py ended with an error (exit code $code)"; exit $code; fi
echo "$(date) friends songs finished"
echo "$(date) back to the pool: analysing the pool_youtube.csv songs still to do"
python -u run_tests.py --list pool_youtube.csv
echo "$(date) pool analysis finished (exit code $?)"
