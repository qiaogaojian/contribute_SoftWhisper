"""
WebWhisper 配置管理模块
集中管理所有配置项，支持从环境变量和配置文件加载
"""

import os
import json
import logging
from pathlib import Path

# 基础路径
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / 'web_config.json'

# 默认配置
DEFAULT_CONFIG = {
    'beam_size': 5,
    'whisper_executable': '',
    'upload_folder': str(BASE_DIR / 'uploads'),
    'temp_folder': str(BASE_DIR / 'temp'),
    'models_folder': str(BASE_DIR / 'models/whisper'),
    'max_upload_size': 500 * 1024 * 1024,  # 500MB
    'allowed_extensions': {'wav', 'mp3', 'm4a', 'flac', 'ogg', 'wma', 'mp4', 'mov', 'avi', 'mkv'},
    'allowed_models': [
        "ggml-tiny.bin", "ggml-tiny.en.bin",
        "ggml-base.bin", "ggml-base.en.bin",
        "ggml-small.bin", "ggml-small.en.bin",
        "ggml-medium.bin", "ggml-medium.en.bin",
        "ggml-large.bin", "ggml-large-v2.bin",
        "ggml-large-v3.bin", "ggml-large-v3-turbo.bin"
    ],
    'host': '0.0.0.0',
    'port': 5000,
    'debug': True
}


class Config:
    """配置管理类"""
    _instance = None
    _config = None

    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self):
        """加载配置"""
        self._config = DEFAULT_CONFIG.copy()
        
        # 从配置文件加载
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r') as f:
                    file_config = json.load(f)
                    self._config.update(file_config)
            except Exception as e:
                logging.error(f"加载配置文件出错: {e}")
        
        # 从环境变量加载
        if os.environ.get('WEBWHISPER_CONFIG'):
            try:
                env_config = json.loads(os.environ.get('WEBWHISPER_CONFIG'))
                self._config.update(env_config)
            except Exception as e:
                logging.error(f"加载环境变量配置出错: {e}")
        
        # 确保目录存在
        os.makedirs(self._config['upload_folder'], exist_ok=True)
        os.makedirs(self._config['temp_folder'], exist_ok=True)
        os.makedirs(self._config['models_folder'], exist_ok=True)
        
        # 设置默认的 whisper 可执行文件路径
        if not self._config['whisper_executable']:
            self._config['whisper_executable'] = self._get_default_whisper_path()

    def _get_default_whisper_path(self):
        """获取默认的 whisper 可执行文件路径"""
        if os.name == "nt":
            # Windows 路径
            whisper_dir = BASE_DIR / "Whisper_win-x64"
            whisper_exe = whisper_dir / "whisper-cli.exe"
        else:
            # Linux 路径
            whisper_dir = BASE_DIR / "Whisper_linux-x64"
            whisper_exe = whisper_dir / "whisper-cli"
        
        # 检查可执行文件是否存在
        if whisper_exe.exists():
            return str(whisper_exe)
        elif whisper_dir.exists():
            return str(whisper_dir)
        else:
            return str(whisper_dir)  # 返回目录路径，即使它不存在

    def save(self):
        """保存配置到文件"""
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self._config, f, indent=4)
            return True
        except Exception as e:
            logging.error(f"保存配置文件出错: {e}")
            return False

    def get(self, key, default=None):
        """获取配置项"""
        return self._config.get(key, default)

    def set(self, key, value):
        """设置配置项"""
        self._config[key] = value
        return self

    def update(self, config_dict):
        """批量更新配置"""
        self._config.update(config_dict)
        return self

    @property
    def as_dict(self):
        """返回配置字典"""
        return self._config.copy()


# 导出配置实例
config = Config() 