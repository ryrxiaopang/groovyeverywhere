#!/bin/bash
# Long unattended pool expansion: search -> analyse -> remove non-songs, repeated for HOURS hours (default 7).
#   nohup bash expand_loop.sh 7 > expand_loop.log 2>&1 &
# Each round runs 20 NEW yt-dlp searches from the generated query set (build_youtube.py --style auto: pop / R&B / indie /
# alternative in the friends' taste, plus K / C / J pop-R&B-indie), up to 10 songs per search (any popularity, at most 4 songs per
# channel overall), analyses them (audio deleted after each song), then runs the audio audit that drops anything that is not a song.
# Stops: when HOURS is used up (no new round starts with under 35 minutes left), after 2 rounds in a row that find nothing new, or
# after 2 build errors in a row. One analysis run at a time: it waits for any other run first. Safe to stop and start again: finished
# searches and analysed songs are skipped.
cd ~/groovyeverywhere || exit 1
source ./env_keys.sh
HOURS="${1:-7}"
END=$(( $(date +%s) + HOURS * 3600 ))
echo "$(date) expansion loop for ${HOURS} h (until $(date -d @$END '+%H:%M'))"
while pgrep -f "[r]un_tests.py" > /dev/null || pgrep -f "[r]un_voice.py" > /dev/null || pgrep -f "[t]aste_boost\.sh" > /dev/null \
      || pgrep -f "[s]potify_boost" > /dev/null || pgrep -f "[p]op_boost\.sh" > /dev/null; do
    sleep 30
done
source .venv/bin/activate
rows() { python -c "import csv;print(sum(1 for r in csv.DictReader(open('pool_youtube.csv',encoding='utf-8-sig')) if (r.get('i_agree') or '').strip().lower() not in ('n','no')))" 2>/dev/null; }
round=0; empty=0; errors=0; start_rows=$(rows)
while [ "$(date +%s)" -lt "$END" ]; do
    left=$(( (END - $(date +%s)) / 60 ))
    if [ "$left" -lt 35 ]; then echo "$(date) only ${left} min left: no new round"; break; fi
    round=$((round + 1)); nq=20; [ "$left" -lt 90 ] && nq=10
    before=$(rows)
    echo "$(date) === round $round ($nq searches, ${left} min left) pool_youtube has $before songs"
    python -u build_youtube.py --ytdlp --style auto --relevance --per 10 --max-views 200000000 --max-queries $nq
    code=$?
    if [ $code -ne 0 ]; then errors=$((errors + 1)); echo "$(date) !! build error (exit code $code), $errors in a row"; else errors=0; fi
    [ "$errors" -ge 2 ] && { echo "$(date) two build errors in a row: stopping"; break; }
    after=$(rows); added=$((after - before))
    echo "$(date) round $round added $added songs"
    if [ "$added" -le 0 ]; then empty=$((empty + 1)); else empty=0; fi
    [ "$empty" -ge 2 ] && { echo "$(date) two rounds found nothing new: stopping"; break; }
    echo "$(date) analysing the new songs"
    python -u run_tests.py --list pool_youtube.csv
    echo "$(date) audio audit"
    python -u audit_pool_audio.py --apply
done
echo "$(date) expansion loop finished after $round rounds: pool_youtube grew from $start_rows to $(rows) songs"

bash quality_pass.sh
