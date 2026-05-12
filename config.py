import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
# On Render, use persistent disk at /data; locally, use instance/ folder
DATABASE = os.environ.get('DATABASE_PATH', os.path.join(BASE_DIR, 'instance', 'app.db'))
HOST_TOKEN = os.environ.get('HOST_TOKEN', 'classroom2026')
