#!/bin/bash
# One unattended run (about 7-8 hours) that grows the pool in two ways, one after the other (one analysis at a time, never two):
#   1. DEEZER:  the next-best related artists (a NEW file deezer_artistsN.json: artists already in the pool are skipped, vetoes are in deezer_skip.txt,
#               your own genre labels in deezer_genres.txt), their songs, analysis, audio audit and quality pass (boost_artists.sh does all of that);
#   2. YOUTUBE: more variety inside the EXISTING genres (build_youtube.py --variety, YouTube Data API: stops cleanly when the daily quota is used up),
#               analysis, audio audit, quality pass.
# It only ADDS songs and never marks anything i_agree = n. Check the result afterwards (pool_summary.py, pool_duplicates.py, ai_channels.py --suggest).
#   nohup bash grow_more.sh [ARTISTS] > grow_more.log 2>&1 &        # ARTISTS = how many Deezer artists (default 40, about 4.5 hours)
#   tail -f grow_more.log                                            # Ctrl+C stops watching, not the run
cd ~/groovyeverywhere || exit 1
source ./env_keys.sh
need_keys YOUTUBE_API_KEY
N="${1:-40}"
START=$(date +%s)
busy() { pgrep -f "[r]un_tests.py" > /dev/null || pgrep -f "[b]oost_artists\.sh" > /dev/null || pgrep -f "[b]oost3\.sh" > /dev/null \
         || pgrep -f "[g]row_pool_overnight\.sh" > /dev/null || pgrep -f "[r]un_voice.py" > /dev/null; }
while busy; do sleep 30; done
echo "$(date) nothing else is running: starting"
source .venv/bin/activate

n=3; while [ -e "deezer_artists$n.json" ]; do n=$((n + 1)); done
OUT="deezer_artists$n.json"
echo "$(date) === 1. Deezer: picking $N artists -> $OUT"
python -u deezer_discover.py --target "$N" --out "$OUT" --since 2018 \
    --quota rock=0 --quota hiphop=0 --quota alternative=15 --quota indierock=20 --quota singer=15 \
    --seed "Faye Webster" --seed "Wallows" --seed "Beach Bunny" --seed "Alvvays" --seed "Gracie Abrams" \
    --seed "Novo Amor" --seed "Lizzy McAlpine" --seed "Holly Humberstone" --seed "The Backseat Lovers" --seed "Julien Baker" 2>&1 | tail -80
if [ "${PIPESTATUS[0]}" -eq 0 ] && [ -s "$OUT" ]; then
    bash boost_artists.sh "$OUT"
else
    echo "$(date) !! the Deezer step failed (no network, or an error above): going on to YouTube"
fi

HOURS=$(( ($(date +%s) - START) / 3600 ))
if [ "$HOURS" -ge 6 ]; then
    echo "$(date) $HOURS hours used: skipping the YouTube step so the run stays within about 8 hours"
else
    echo "$(date) === 2. YouTube: more variety inside the existing genres"
    while busy; do sleep 30; done
    python -u build_youtube.py --variety --per 10 --pages 1
    code=$?
    if [ $code -ne 0 ]; then echo "$(date) !! build_youtube.py ended with exit code $code (the quota is often the reason); what it found is saved"; fi
    echo "$(date) analysing the pool_youtube.csv songs still to do"
    python -u run_tests.py --list pool_youtube.csv
    echo "$(date) audio audit: removing anything that is not a song"
    python -u audit_pool_audio.py --apply
    bash quality_pass.sh
fi
echo "$(date) === the pool now:"
python pool_summary.py 2>&1 | head -40
echo "$(date) grow_more finished (about $(( ($(date +%s) - START) / 3600 )) hours)"
