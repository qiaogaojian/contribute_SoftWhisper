"""
WebWhisper 应用入口模块
初始化 Flask 应用
"""
import os
import logging

from pycore.base import Core
from pycore.logger import Logger
from pycore.utils.tools import Tools
from pycore.utils.file_utils import FileUtils

from flask import Flask, render_template
from flask_socketio import SocketIO

from webwhisper.utils.logging_utils import logger
from webwhisper.api.routes import api
from webwhisper.api.websocket import websocket_namespace
from webwhisper.config import config


def create_app():
    """
    创建 Flask 应用
    
    Returns:
        Flask: Flask 应用实例
    """
    # 创建 Flask 应用
    app = Flask(__name__)
    
    # 配置应用
    app.secret_key = os.urandom(24)
    app.config['UPLOAD_FOLDER'] = config.get('upload_folder')
    app.config['MAX_CONTENT_LENGTH'] = config.get('max_upload_size')
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SESSION_PERMANENT'] = True
    app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 会话有效期1小时
    
    # 注册蓝图
    app.register_blueprint(api)
    
    # 主页路由
    @app.route('/')
    def index():
        """主页"""
        return render_template('index.html', 
                              models=config.get('allowed_models'),
                              config=config.as_dict)
    
    return app


def create_socketio(app):
    """
    创建 SocketIO 实例
    
    Args:
        app: Flask 应用实例
    
    Returns:
        SocketIO: SocketIO 实例
    """
    # 创建 SocketIO 实例
    socketio = SocketIO(app, manage_session=False)
    
    # 注册命名空间
    socketio.on_namespace(websocket_namespace)
    
    return socketio


def main():
    """应用入口函数"""
    # 创建应用
    app = create_app()
    socketio = create_socketio(app)
    
    # 确保必要的目录存在
    os.makedirs(config.get('upload_folder'), exist_ok=True)
    os.makedirs(config.get('temp_folder'), exist_ok=True)
    os.makedirs(config.get('models_folder'), exist_ok=True)
    
    # 检查模板目录是否存在
    templates_dir = FileUtils.get_project_path("templates")
    if not os.path.exists(templates_dir):
        logger.warning("模板目录不存在，将使用默认模板")
    
    # 启动服务器
    logger.info("启动 WebWhisper...")
    logger.info(f"使用配置: {config.as_dict}")
    
    socketio.run(
        app,
        host=config.get('host'),
        port=config.get('port'),
        debug=config.get('debug')
    )


if __name__ == '__main__':
    args = Tools.parse_args()
    core = Core()
    core.init(env=args.env)
    Logger.instance().info('********************************* Web Whisper *********************************')

    main() 