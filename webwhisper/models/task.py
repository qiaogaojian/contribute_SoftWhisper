"""
WebWhisper 任务数据模型
定义转录任务的数据结构
"""

import time
import threading
import queue
from enum import Enum


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


class TranscriptionTask:
    """转录任务类"""
    
    def __init__(self, task_id, file_path, options=None):
        """
        初始化转录任务
        
        Args:
            task_id: 任务ID
            file_path: 文件路径
            options: 转录选项
        """
        self.task_id = task_id
        self.file_path = file_path
        self.options = options or {}
        self.status = TaskStatus.PENDING
        self.progress = 0
        self.message = "等待开始"
        self.result = None
        self.error = None
        self.created_at = time.time()
        self.updated_at = time.time()
        self.completed_at = None
        
        # 用于进度通信和任务控制
        self.progress_queue = queue.Queue()
        self.stop_event = threading.Event()
    
    def update_progress(self, progress, message=None):
        """
        更新进度
        
        Args:
            progress: 进度百分比
            message: 进度消息
        """
        self.progress = progress
        if message:
            self.message = message
        self.updated_at = time.time()
        
        # 将进度放入队列
        self.progress_queue.put({
            'progress': progress,
            'message': message or self.message
        })
    
    def cancel(self):
        """取消任务"""
        self.status = TaskStatus.CANCELLED
        self.stop_event.set()
        self.message = "任务已取消"
        self.updated_at = time.time()
    
    def complete(self, result):
        """
        完成任务
        
        Args:
            result: 任务结果
        """
        self.status = TaskStatus.COMPLETED
        self.result = result
        self.progress = 100
        self.message = "任务已完成"
        self.updated_at = time.time()
        self.completed_at = time.time()
    
    def fail(self, error):
        """
        任务失败
        
        Args:
            error: 错误信息
        """
        self.status = TaskStatus.ERROR
        self.error = error
        self.message = f"任务失败: {error}"
        self.updated_at = time.time()
    
    def start(self):
        """开始任务"""
        self.status = TaskStatus.RUNNING
        self.message = "任务运行中"
        self.updated_at = time.time()
    
    def to_dict(self):
        """
        转换为字典
        
        Returns:
            dict: 任务字典
        """
        return {
            'task_id': self.task_id,
            'file_path': self.file_path,
            'status': self.status.value,
            'progress': self.progress,
            'message': self.message,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'completed_at': self.completed_at,
            'has_result': self.result is not None,
            'has_error': self.error is not None
        }
    
    def get_result_dict(self):
        """
        获取结果字典
        
        Returns:
            dict: 结果字典
        """
        if self.status == TaskStatus.COMPLETED:
            return {
                'success': True,
                'status': self.status.value,
                'text': self.result.get('text', ''),
                'segments': self.result.get('segments', [])
            }
        elif self.status == TaskStatus.ERROR:
            return {
                'success': False,
                'status': self.status.value,
                'error': self.error
            }
        else:
            return {
                'success': True,
                'status': self.status.value,
                'progress': self.progress,
                'message': self.message
            } 