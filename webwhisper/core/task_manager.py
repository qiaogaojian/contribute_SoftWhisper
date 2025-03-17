"""
WebWhisper 任务管理模块
处理转录任务的创建、执行和管理
"""

import os
import time
import threading
import queue
from collections import OrderedDict

from webwhisper.utils.logging_utils import logger
from webwhisper.utils.whisper_utils import transcribe_audio
from webwhisper.models.task import TranscriptionTask, TaskStatus


class TaskManager:
    """任务管理器类"""
    
    def __init__(self, max_tasks=100):
        """
        初始化任务管理器
        
        Args:
            max_tasks: 最大任务数量
        """
        self.tasks = OrderedDict()  # 使用有序字典，便于清理旧任务
        self.max_tasks = max_tasks
        self.lock = threading.Lock()  # 用于线程安全
    
    def create_task(self, task_id, file_path, options):
        """
        创建任务
        
        Args:
            task_id: 任务ID
            file_path: 文件路径
            options: 转录选项
        
        Returns:
            TranscriptionTask: 任务对象
        """
        with self.lock:
            # 检查文件是否存在
            if not os.path.exists(file_path):
                logger.error(f"文件不存在: {file_path}")
                task = TranscriptionTask(task_id, file_path, options)
                task.fail("文件不存在")
                self.tasks[task_id] = task
                return task
            
            # 创建任务
            task = TranscriptionTask(task_id, file_path, options)
            self.tasks[task_id] = task
            
            # 清理旧任务，保持任务数量在限制内
            self._clean_old_tasks()
            
            logger.info(f"已创建任务: {task_id}, 文件: {file_path}")
            return task
    
    def start_task(self, task_id):
        """
        启动任务
        
        Args:
            task_id: 任务ID
        
        Returns:
            bool: 是否成功启动
        """
        with self.lock:
            if task_id not in self.tasks:
                logger.error(f"任务不存在: {task_id}")
                return False
            
            task = self.tasks[task_id]
            
            # 如果任务已经在运行或已完成，不再启动
            if task.status in [TaskStatus.RUNNING, TaskStatus.COMPLETED]:
                return False
            
            # 标记任务为运行状态
            task.start()
        
        # 启动转录线程
        thread = threading.Thread(
            target=self._run_transcription,
            args=(task_id,)
        )
        thread.daemon = True
        thread.start()
        
        logger.info(f"已启动任务: {task_id}")
        return True
    
    def _run_transcription(self, task_id):
        """
        执行转录任务
        
        Args:
            task_id: 任务ID
        """
        with self.lock:
            if task_id not in self.tasks:
                logger.error(f"任务不存在: {task_id}")
                return
            
            task = self.tasks[task_id]
        
        try:
            # 定义进度回调函数
            def progress_callback(progress, message):
                logger.debug(f"进度更新: {progress}%, 消息: {message}")
                task.update_progress(progress, message)
            
            # 执行转录
            logger.info(f"开始转录任务: {task_id}, 文件: {task.file_path}")
            result = transcribe_audio(
                file_path=task.file_path,
                options=task.options,
                progress_callback=progress_callback,
                stop_event=task.stop_event
            )
            
            # 处理结果
            with self.lock:
                if task_id not in self.tasks:
                    return
                
                task = self.tasks[task_id]
                
                if task.stop_event.is_set():
                    task.status = TaskStatus.CANCELLED
                    logger.info(f"任务已取消: {task_id}")
                elif result.get('cancelled', False):
                    task.fail(result.get('text', '转录失败'))
                    logger.error(f"任务失败: {task_id}, 错误: {task.error}")
                else:
                    task.complete(result)
                    logger.info(f"任务完成: {task_id}")
            
            # 清理临时文件
            temp_audio_path = result.get('temp_audio_path')
            if temp_audio_path and os.path.exists(temp_audio_path):
                try:
                    os.remove(temp_audio_path)
                    logger.debug(f"已删除临时文件: {temp_audio_path}")
                except:
                    logger.warning(f"无法删除临时文件: {temp_audio_path}")
        
        except Exception as e:
            logger.error(f"转录任务异常: {task_id}, 错误: {str(e)}")
            with self.lock:
                if task_id in self.tasks:
                    self.tasks[task_id].fail(str(e))
    
    def cancel_task(self, task_id):
        """
        取消任务
        
        Args:
            task_id: 任务ID
        
        Returns:
            bool: 是否成功取消
        """
        with self.lock:
            if task_id not in self.tasks:
                logger.error(f"任务不存在: {task_id}")
                return False
            
            task = self.tasks[task_id]
            
            # 只有运行中的任务可以取消
            if task.status != TaskStatus.RUNNING:
                return False
            
            task.cancel()
            logger.info(f"已取消任务: {task_id}")
            return True
    
    def get_task(self, task_id):
        """
        获取任务
        
        Args:
            task_id: 任务ID
        
        Returns:
            TranscriptionTask: 任务对象
        """
        with self.lock:
            return self.tasks.get(task_id)
    
    def get_task_status(self, task_id):
        """
        获取任务状态
        
        Args:
            task_id: 任务ID
        
        Returns:
            dict: 任务状态字典
        """
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return {'success': False, 'error': '任务不存在'}
            
            return task.to_dict()
    
    def get_task_result(self, task_id):
        """
        获取任务结果
        
        Args:
            task_id: 任务ID
        
        Returns:
            dict: 任务结果字典
        """
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return {'success': False, 'error': '任务不存在'}
            
            return task.get_result_dict()
    
    def _clean_old_tasks(self):
        """
        清理旧任务，保持任务数量在限制内
        """
        if len(self.tasks) <= self.max_tasks:
            return
        
        # 按创建时间排序，删除最旧的任务
        tasks_by_time = sorted(
            self.tasks.items(),
            key=lambda x: x[1].created_at
        )
        
        # 删除超出限制的任务
        for task_id, _ in tasks_by_time[:len(tasks_by_time) - self.max_tasks]:
            del self.tasks[task_id]
            logger.info(f"已清理旧任务: {task_id}")
    
    def clean_completed_tasks(self, max_age_hours=24):
        """
        清理已完成的旧任务
        
        Args:
            max_age_hours: 最大保留时间（小时）
        
        Returns:
            int: 清理的任务数量
        """
        with self.lock:
            count = 0
            now = time.time()
            max_age_seconds = max_age_hours * 3600
            
            # 找出需要删除的任务
            to_delete = []
            for task_id, task in self.tasks.items():
                if task.status in [TaskStatus.COMPLETED, TaskStatus.ERROR, TaskStatus.CANCELLED]:
                    if task.updated_at < now - max_age_seconds:
                        to_delete.append(task_id)
            
            # 删除任务
            for task_id in to_delete:
                del self.tasks[task_id]
                count += 1
                logger.info(f"已清理完成的旧任务: {task_id}")
            
            return count


# 导出任务管理器实例
task_manager = TaskManager() 