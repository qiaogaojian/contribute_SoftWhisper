"""
WebWhisper 日志工具模块
提供统一的日志记录功能
"""

import os
import sys
import logging
from pathlib import Path
from datetime import datetime

# 日志级别映射
LOG_LEVELS = {
    'debug': logging.DEBUG,
    'info': logging.INFO,
    'warning': logging.WARNING,
    'error': logging.ERROR,
    'critical': logging.CRITICAL
}

# 日志格式
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# 日志目录
LOG_DIR = Path(__file__).resolve().parent.parent.parent / 'logs'


def setup_logger(name, level='info', log_file=None, console=True):
    """
    设置日志记录器
    
    Args:
        name: 日志记录器名称
        level: 日志级别
        log_file: 日志文件路径
        console: 是否输出到控制台
    
    Returns:
        logger: 日志记录器
    """
    # 创建日志记录器
    logger = logging.getLogger(name)
    logger.setLevel(LOG_LEVELS.get(level.lower(), logging.INFO))
    
    # 清除现有处理器
    logger.handlers = []
    
    # 创建格式化器
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    
    # 添加文件处理器
    if log_file:
        # 确保日志目录存在
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    # 添加控制台处理器
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    return logger


def get_default_logger(name='webwhisper', level='info'):
    """
    获取默认日志记录器
    
    Args:
        name: 日志记录器名称
        level: 日志级别
    
    Returns:
        logger: 日志记录器
    """
    # 确保日志目录存在
    os.makedirs(LOG_DIR, exist_ok=True)
    
    # 创建日志文件路径
    log_file = LOG_DIR / f"{name}_{datetime.now().strftime('%Y%m%d')}.log"
    
    return setup_logger(name, level, log_file)


# 导出默认日志记录器
logger = get_default_logger()


def debug_print(msg):
    """
    调试打印函数，直接输出到标准输出
    兼容旧代码
    
    Args:
        msg: 调试消息
    """
    sys.__stdout__.write(f"DEBUG: {msg}\n")
    sys.__stdout__.flush()
    logger.debug(msg) 