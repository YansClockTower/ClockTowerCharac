from flask import Flask

def create_app():
    app = Flask(__name__)

    # 注册过滤器
    from .filter import format_timestamp, team_label_filter

    app.add_template_filter(format_timestamp, 'datetime')
    app.add_template_filter(team_label_filter, 'team_name')
    
    # 注册 blueprint
    from .views.character_info import character_bp
    from .views.build_edition import buildedition_bp
    app.register_blueprint(character_bp)
    app.register_blueprint(buildedition_bp)

    # 注册首页路由
    from .route import register_routes
    register_routes(app)

    return app
