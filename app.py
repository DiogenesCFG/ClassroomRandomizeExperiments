import os
from flask import Flask
from flask_socketio import SocketIO

socketio = SocketIO()


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object('config')

    # Ensure instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)

    # Initialize SocketIO
    socketio.init_app(app, async_mode='threading', cors_allowed_origins='*')

    # Initialize database
    from models.db import close_db, init_db_command
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)

    # Register blueprints
    from routes import register_blueprints
    register_blueprints(app)

    # Register SocketIO events
    from sockets import register_events
    register_events(socketio)

    return app
