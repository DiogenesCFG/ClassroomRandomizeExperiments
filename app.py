import logging
import os

from flask import Flask
from flask_socketio import SocketIO

socketio = SocketIO()


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object('config')

    # Ensure logs are visible in Render
    logging.basicConfig(level=logging.INFO)
    app.logger.setLevel(logging.INFO)

    # Ensure instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)

    # Initialize SocketIO
    # Use eventlet on Render (production), threading locally (development)
    async_mode = os.environ.get('ASYNC_MODE', 'threading')
    socketio.init_app(
        app,
        async_mode=async_mode,
        cors_allowed_origins='*',
        ping_timeout=60,
        ping_interval=25,
    )

    # Initialize database
    from models.db import close_db, init_db_command, init_db
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)

    # Auto-create tables on startup if they don't exist
    with app.app_context():
        init_db()

    # Register blueprints
    from routes import register_blueprints
    register_blueprints(app)

    # Register SocketIO events
    from sockets import register_events
    register_events(socketio)

    return app


# Module-level app instance for gunicorn (gunicorn app:app)
app = create_app()
