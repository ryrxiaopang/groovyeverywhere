#!/bin/bash
# After the Voice development run finishes (one analysis run at a time):
#   1. Voice-alone development analysis  (voice_dev_analysis.py -> voice_dev_report.md)
#   2. Sound numbers for the same development songs (needed for the Sound vs Sound + Voice dry run)
#   3. the dry run (voice_dev_analysis.py --with-sound -> voice_dev_report.md again, with the Sound comparison)
#   4. the 28 new YouTube songs of the pool
#   nohup bash after_voice.sh > after_voice.log 2>&1 &
cd ~/groovyeverywhere || exit 1
source ./env_keys.sh
need_keys JAMENDO_CLIENT_ID
while pgrep -f "[r]un_voice.py" > /dev/null || pgrep -f "[b]uild_youtube.py" > /dev/null; do
    sleep 30
done
source .venv/bin/activate
echo "$(date) Voice run finished: $(ls results/voice/*.npz | wc -l) songs. Voice-alone development analysis:"
python voice_dev_analysis.py > voice_dev_analysis.log 2>&1
echo "$(date) analysis exit code $?  (voice_dev_report.md)"
echo "$(date) analysing Sound for the development songs"
python -u run_tests.py --list voice_dev.csv
code=$?
if [ $code -ne 0 ]; then echo "$(date) !! run_tests.py (voice_dev.csv) ended with an error (exit code $code)"; fi
python voice_dev_analysis.py --with-sound > voice_dev_analysis_with_sound.log 2>&1
echo "$(date) analysis with Sound exit code $?  (voice_dev_report.md)"
echo "$(date) analysing the new pool_youtube.csv songs"
python -u run_tests.py --list pool_youtube.csv
echo "$(date) finished (exit code $?)"
