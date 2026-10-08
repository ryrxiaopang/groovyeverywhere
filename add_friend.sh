#!/bin/bash
# Analyse the songs just added to friends_songs.csv (+ anything pending in pool_youtube.csv), remove non-songs, then build the new
# friend's FINAL lists and listening sheet (existing friends' captures and sheets are never touched).
#   bash add_friend.sh Javen
cd ~/groovyeverywhere || exit 1
FRIEND="${1:?usage: add_friend.sh FRIEND_NAME}"
source ./env_keys.sh
while pgrep -f "[r]un_tests.py" > /dev/null; do sleep 20; done
source .venv/bin/activate
echo "$(date) analysing the friend's songs"
python -u run_tests.py --list friends_songs.csv
echo "$(date) analysing new pool songs (if any)"
python -u run_tests.py --list pool_youtube.csv
echo "$(date) audio audit"
python -u audit_pool_audio.py --apply
echo "$(date) building $FRIEND's lists (final)"
python -u build_friend_lists.py --final --friend "$FRIEND"
python blind_test.py --sheets
python -u add_listen_links.py
echo "$(date) done: blind_sheets/"
ls -la blind_sheets
