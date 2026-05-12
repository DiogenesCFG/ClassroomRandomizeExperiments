"""Standalone script to initialize the database."""
from app import app
from models.db import init_db

with app.app_context():
    init_db()
    print('Database initialized.')
