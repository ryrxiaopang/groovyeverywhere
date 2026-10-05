#!/usr/bin/env bash
# One-time PostgreSQL + pgvector setup inside Ubuntu (WSL2). Run from hidden-gems-tests:
#   bash setup_db.sh
# Creates database "hiddengems" with user "hg" (password "hg", local only), installs the
# Python drivers, saves HG_DB in ~/.bashrc and imports everything already in results/.
set -e
cd "$(dirname "$0")"

echo "== 1/5 install PostgreSQL"
sudo apt update -qq
sudo apt install -y -qq postgresql postgresql-contrib
V=$(ls /usr/lib/postgresql | sort -V | tail -1)
echo "   PostgreSQL version $V"

echo "== 2/5 install pgvector for PostgreSQL $V"
if ! sudo apt install -y -qq "postgresql-$V-pgvector"; then
  echo "!! package postgresql-$V-pgvector not found."
  echo "   Add the official PostgreSQL repository, then rerun this script:"
  echo "   sudo apt install -y postgresql-common && sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y"
  exit 1
fi

echo "== 3/5 start the database and create user + database"
sudo service postgresql start
sudo -u postgres psql -qtc "SELECT 1 FROM pg_roles WHERE rolname='hg'" | grep -q 1 || \
  sudo -u postgres psql -qc "CREATE ROLE hg LOGIN PASSWORD 'hg'"
sudo -u postgres psql -qtc "SELECT 1 FROM pg_database WHERE datname='hiddengems'" | grep -q 1 || \
  sudo -u postgres psql -qc "CREATE DATABASE hiddengems OWNER hg"
sudo -u postgres psql -q -d hiddengems -c "CREATE EXTENSION IF NOT EXISTS vector"

echo "== 4/5 Python drivers"
source .venv/bin/activate
pip install -q "psycopg[binary]" pgvector
grep -q HG_DB ~/.bashrc || echo 'export HG_DB=postgresql://hg:hg@localhost:5432/hiddengems' >> ~/.bashrc
export HG_DB=postgresql://hg:hg@localhost:5432/hiddengems

echo "== 5/5 import existing results"
python import_results.py
echo
echo "Done. Try:  python similar.py 959961"
echo "Note: after a PC restart, start the database again with:  sudo service postgresql start"
