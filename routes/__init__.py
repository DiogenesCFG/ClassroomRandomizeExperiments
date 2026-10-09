def register_blueprints(app):
    from routes.main import bp as main_bp
    from routes.classroom import bp as classroom_bp
    from routes.builder import bp as builder_bp
    from routes.student import bp as student_bp
    from routes.host import bp as host_bp
    from routes.download import bp as download_bp
    from routes.roster import bp as roster_bp
    from routes.account import bp as account_bp
    from routes.feedback import bp as feedback_bp
    from routes.reminders import bp as reminders_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(classroom_bp)
    app.register_blueprint(builder_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(host_bp)
    app.register_blueprint(download_bp)
    app.register_blueprint(roster_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(feedback_bp)
    app.register_blueprint(reminders_bp)

    @app.context_processor
    def nav_links():
        """Navbar links for pages inside a classroom: the student's lobby + sign out,
        and/or the instructor home + log out (a browser can be both)."""
        from flask import request, session
        code = (request.view_args or {}).get('code')
        if not code:
            return {'nav': None}
        from models.classroom import get_classroom_by_code
        from routes.account import get_signed_in_student
        classroom = get_classroom_by_code(code)
        if not classroom:
            return {'nav': None}
        student = get_signed_in_student(classroom)
        return {'nav': {'code': classroom['code'],
                        'student': student,
                        'host': session.get(f'host_authenticated_{classroom["id"]}') is True}}
