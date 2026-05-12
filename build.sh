#!/usr/bin/env bash
# Render build script
set -o errexit

pip install -r requirements.txt

# Initialize the database (creates tables if they don't exist, runs migrations)
python init_db.py
