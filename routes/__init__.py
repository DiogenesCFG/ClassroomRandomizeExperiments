def register_blueprints(app):
    from routes.main import bp as main_bp
    from routes.builder import bp as builder_bp
    from routes.student import bp as student_bp
    from routes.host import bp as host_bp
    from routes.download import bp as download_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(builder_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(host_bp)
    app.register_blueprint(download_bp)
