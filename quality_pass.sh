#!/bin/bash
# Keep the pool listenable and honest after songs were added: (1) every song has a working link, (2) a YouTube alternative where the page
# is gone, (3) AI-generated songs are tagged. Cheap to repeat: only NEW songs are link-checked; tagging uses the YouTube API (~100 units).
#   bash quality_pass.sh
cd ~/groovyeverywhere || exit 1
source ./env_keys.sh
source .venv/bin/activate
python -u check_pool_links.py
python -u find_youtube_alternatives.py
python -u tag_ai.py
python -u mark_ai_out.py --apply        # AI-tagged songs and blocked channels leave the pool lists for good (ai_keep.txt wins; undo: mark_ai_out.py --restore)
echo "$(date) quality pass done"
