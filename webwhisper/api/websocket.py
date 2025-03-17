"""
WebWhisper WebSocket 模块
处理实时通信
"""

import threading
import time
import queue
from flask_socketio import Namespace, emit
from flask import request

from webwhisper.utils.logging_utils import logger
from webwhisper.core.task_manager import task_manager
from webwhisper.models.task import TaskStatus


class WebWhisperNamespace(Namespace):
    """WebWhisper WebSocket 命名空间"""
    
    def __init__(self, namespace='/'):
        """
        初始化 WebSocket 命名空间
        
        Args:
            namespace: 命名空间
        """
        super(WebWhisperNamespace, self).__init__(namespace)
        self.clients = {}  # 客户端会话字典
        self.progress_threads = {}  # 进度线程字典
    
    def on_connect(self, auth=None):
        """
        处理客户端连接
        
        Args:
            auth: 认证信息（Flask-SocketIO 4.x 版本需要）
        """
        client_id = request.sid
        self.clients[client_id] = {
            'connected_at': time.time(),
            'task_id': None
        }
        logger.info(f"客户端已连接: {client_id}")
    
    def on_disconnect(self):
        """处理客户端断开连接"""
        client_id = request.sid
        if client_id in self.clients:
            # 停止进度线程
            if client_id in self.progress_threads:
                self.progress_threads[client_id]['stop'] = True
                del self.progress_threads[client_id]
            
            # 删除客户端记录
            del self.clients[client_id]
        
        logger.info(f"客户端已断开连接: {client_id}")
    
    def on_subscribe_task(self, data):
        """
        订阅任务进度
        
        Args:
            data: 包含任务ID的字典
        """
        client_id = request.sid
        task_id = data.get('task_id')
        
        if not task_id:
            emit('error', {'message': '无效的任务ID'})
            return
        
        # 获取任务
        task = task_manager.get_task(task_id)
        if not task:
            emit('error', {'message': '任务不存在'})
            return
        
        # 更新客户端记录
        self.clients[client_id]['task_id'] = task_id
        
        # 如果任务已完成，直接发送完成通知
        if task.status == TaskStatus.COMPLETED:
            emit('transcription_completed', {
                'task_id': task_id,
                'text': task.result.get('text', ''),
                'has_segments': len(task.result.get('segments', [])) > 0
            })
            return
        
        # 如果任务已失败，直接发送错误通知
        if task.status == TaskStatus.ERROR:
            emit('transcription_error', {
                'task_id': task_id,
                'error': task.error
            })
            return
        
        # 如果任务已取消，直接发送取消通知
        if task.status == TaskStatus.CANCELLED:
            emit('transcription_cancelled', {
                'task_id': task_id
            })
            return
        
        # 启动进度监控线程
        if client_id not in self.progress_threads:
            self.progress_threads[client_id] = {
                'thread': threading.Thread(
                    target=self._monitor_progress,
                    args=(client_id, task_id)
                ),
                'stop': False
            }
            self.progress_threads[client_id]['thread'].daemon = True
            self.progress_threads[client_id]['thread'].start()
        
        # 发送当前进度
        emit('progress_update', {
            'task_id': task_id,
            'progress': task.progress,
            'message': task.message
        })
    
    def on_unsubscribe_task(self, data):
        """
        取消订阅任务进度
        
        Args:
            data: 包含任务ID的字典
        """
        client_id = request.sid
        
        # 停止进度线程
        if client_id in self.progress_threads:
            self.progress_threads[client_id]['stop'] = True
            del self.progress_threads[client_id]
        
        # 更新客户端记录
        if client_id in self.clients:
            self.clients[client_id]['task_id'] = None
    
    def _monitor_progress(self, client_id, task_id):
        """
        监控任务进度
        
        Args:
            client_id: 客户端ID
            task_id: 任务ID
        """
        try:
            # 获取任务
            task = task_manager.get_task(task_id)
            if not task:
                return
            
            # 监控进度队列
            while client_id in self.clients and client_id in self.progress_threads:
                # 检查是否应该停止
                if self.progress_threads[client_id]['stop']:
                    break
                
                # 检查任务状态
                task = task_manager.get_task(task_id)
                if not task:
                    break
                
                # 如果任务已完成，发送完成通知
                if task.status == TaskStatus.COMPLETED:
                    emit('transcription_completed', {
                        'task_id': task_id,
                        'text': task.result.get('text', ''),
                        'has_segments': len(task.result.get('segments', [])) > 0
                    }, namespace='/', to=client_id)
                    break
                
                # 如果任务已失败，发送错误通知
                if task.status == TaskStatus.ERROR:
                    emit('transcription_error', {
                        'task_id': task_id,
                        'error': task.error
                    }, namespace='/', to=client_id)
                    break
                
                # 如果任务已取消，发送取消通知
                if task.status == TaskStatus.CANCELLED:
                    emit('transcription_cancelled', {
                        'task_id': task_id
                    }, namespace='/', to=client_id)
                    break
                
                # 尝试从队列获取进度更新
                try:
                    progress_data = task.progress_queue.get(timeout=0.5)
                    emit('progress_update', {
                        'task_id': task_id,
                        'progress': progress_data['progress'],
                        'message': progress_data['message']
                    }, namespace='/', to=client_id)
                except queue.Empty:
                    # 队列为空，继续等待
                    pass
                
                # 短暂休眠，避免过度消耗CPU
                time.sleep(0.1)
        
        except Exception as e:
            logger.error(f"监控进度线程异常: {str(e)}")
        
        finally:
            # 清理线程记录
            if client_id in self.progress_threads:
                del self.progress_threads[client_id]


# 导出 WebSocket 命名空间
websocket_namespace = WebWhisperNamespace() 