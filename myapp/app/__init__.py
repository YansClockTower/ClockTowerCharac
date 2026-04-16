from flask import Flask
from flask_cors import CORS


def create_app():
    app = Flask(__name__, static_url_path='/static', static_folder='static')
    from .models.config import get_config
    from .identity.permissions import ensure_user_permission_schema
    app.config["SECRET_KEY"] = get_config("secret_key")
    ensure_user_permission_schema()

    CORS(app,
     supports_credentials=True,
     origins=["http://localhost:8080", "https://yanice.online"])  # 允许前端地址

    # 注册过滤器
    from .filter import format_timestamp, team_label_filter, team_color_filter, edition_name_filter

    app.add_template_filter(format_timestamp, 'datetime')
    app.add_template_filter(team_label_filter, 'team_name')
    app.add_template_filter(team_color_filter, 'team_color')
    app.add_template_filter(edition_name_filter, 'edition_name')

    # 注册 blueprint
    from .subsystems.editions.character_info import character_bp
    from .subsystems.editions.build_edition import buildedition_bp
    from .subsystems.editions.view_edition import viewedition_bp
    from .subsystems.editions.api import api_bp
    from .views.users import users_bp
    from .portal.routes import portal_bp
    from .subsystems.events.routes import events_bp
    from .subsystems.events.dbutil import close_db as close_events_db

    app.register_blueprint(api_bp)
    app.register_blueprint(character_bp)
    app.register_blueprint(buildedition_bp)
    app.register_blueprint(viewedition_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(portal_bp)

    app.teardown_appcontext(close_events_db)

    return app
