#!/bin/bash
# After the current analysis run has finished (one run at a time): add songs in the Fujii Kaze style (Japanese soul /
# piano pop / city pop, inside the EXISTING genres jpop, jrnb, citypop, singer, rnb) with yt-dlp searches (no API quota),
# then analyse them.      nohup bash style_boost.sh > style_boost.log 2>&1 &
cd ~/groovyeverywhere || exit 1
source ./env_keys.sh
while pgrep -f "[r]un_tests.py" > /dev/null || pgrep -f "[r]un_voice.py" > /dev/null || pgrep -f "[a]nalyse_list_then_pool" > /dev/null; do
    sleep 30
done
echo "$(date) other runs finished: searching with yt-dlp"
source .venv/bin/activate
python -u build_youtube.py --ytdlp --per 10 --max-views 400000
code=$?
if [ $code -ne 0 ]; then echo "$(date) !! build_youtube.py ended with an error (exit code $code); what it found is saved"; fi
echo "$(date) analysing the pool_youtube.csv songs still to do"
python -u run_tests.py --list pool_youtube.csv
echo "$(date) style boost finished (exit code $?)"
