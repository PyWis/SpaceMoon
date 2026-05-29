from flask import Flask
from config import Config
from app.extensions import db, login_manager, socketio


def create_app(config_class=Config, async_mode='threading'):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    socketio.init_app(app, cors_allowed_origins='*', async_mode=async_mode)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Effettua il login per accedere.'
    login_manager.login_message_category = 'warning'

    from app.routes.auth      import auth_bp
    from app.routes.admin     import admin_bp
    from app.routes.game      import game_bp
    from app.routes.dashboard import dashboard_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp,     url_prefix='/admin')
    app.register_blueprint(game_bp,      url_prefix='/game')
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard')

    # Custom Jinja2 filters
    app.jinja_env.filters['enumerate'] = enumerate

    return app
