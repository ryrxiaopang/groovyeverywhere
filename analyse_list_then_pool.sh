#!/bin/bash
# Analyse ONE small song list first (e.g. a song you want recommendations for), then carry on with the pool backlog.
# Waits for any other analysis run to finish first (one run at a time).
#   nohup bash analyse_list_then_pool.sh queries_songs.csv > analyse_list.log 2>&1 &
cd ~/groovyeverywhere || exit 1
LIST="${1:?usage: analyse_list_then_pool.sh LIST.csv}"
source ./env_keys.sh
while pgrep -f "[r]un_tests.py" > /dev/null || pgrep -f "[r]un_voice.py" > /dev/null; do
    sleep 20
done
echo "$(date) analysing $LIST"
source .venv/bin/activate
python -u run_tests.py --list "$LIST"
code=$?
echo "$(date) $LIST finished (exit code $code)"
echo "$(date) back to the pool: analysing the pool_youtube.csv songs still to do"
python -u run_tests.py --list pool_youtube.csv
echo "$(date) pool analysis finished (exit code $?)"
