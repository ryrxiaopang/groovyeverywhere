#!/usr/bin/env bash
# One-shot setup for a new machine (Ubuntu / WSL2). Run from inside hidden-gems-tests:
#   bash setup.sh
# Safe to run again: every step skips what is already done.
set -e
cd "$(dirname "$0")"

echo "== 1/6 system packages (asks for your Ubuntu password)"
sudo apt update -qq && sudo apt install -y -qq python3-venv python3-pip unzip wget

echo "== 2/6 Python environment"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install --resume-retries 10 --timeout 120 -r requirements.txt

echo "== 3/6 models (about 60 MB; resumes if the server is slow)"
python -c "import models; [print(f'{models.BASE}/{p}{e}') for p,_ in models.MODELS.values() for e in ('.pb','.json')]" > model_urls.txt
wget -c -q --show-progress --tries=20 --timeout=30 -P models -i model_urls.txt
python models.py

echo "== 4/6 quiet TensorFlow messages"
grep -q TF_CPP_MIN_LOG_LEVEL ~/.bashrc || echo 'export TF_CPP_MIN_LOG_LEVEL=2' >> ~/.bashrc

echo "== 5/6 Jamendo client ID"
if ! grep -q JAMENDO_CLIENT_ID ~/.bashrc; then
  read -rp "Paste your Jamendo client ID (8 characters): " CID
  echo "export JAMENDO_CLIENT_ID=$CID" >> ~/.bashrc
fi

export JAMENDO_CLIENT_ID=$(grep JAMENDO_CLIENT_ID ~/.bashrc | tail -1 | cut -d= -f2)
if curl -s "https://api.jamendo.com/v3.0/tracks/?client_id=$JAMENDO_CLIENT_ID&format=json&limit=1&id=959961" | grep -q '"status":"success"'; then
  echo "Jamendo ID works"
else
  echo "!! Jamendo ID rejected - fix the line in ~/.bashrc (nano ~/.bashrc), then rerun this script"
fi

echo "== 6/6 self-check"
python synthetic_tests.py | tail -3
echo
echo "Setup done. Start the tests with:"
echo "  source .venv/bin/activate && nohup python -u run_tests.py > run.log 2>&1 &"
