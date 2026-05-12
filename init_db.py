"""Standalone script to initialize the database."""
from app import create_app
from models.db import init_db

app = create_app()
with app.app_context():
    init_db()
    print('Database initialized.')
