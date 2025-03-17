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
        logger.info(f"WebSocket 命名空间已初始化: {namespace}")
    
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
        logger.info(f"客户端已连接: {client_id}, 当前客户端数: {len(self.clients)}")
    
    def on_disconnect(self):
        """处理客户端断开连接"""
        client_id = request.sid
        if client_id in self.clients:
            task_id = self.clients[client_id].get('task_id')
            logger.info(f"客户端断开连接: {client_id}, 关联任务ID: {task_id}")
            
            # 停止进度线程
            if client_id in self.progress_threads:
                logger.debug(f"停止客户端 {client_id} 的进度监控线程")
                self.progress_threads[client_id]['stop'] = True
                del self.progress_threads[client_id]
            
            # 删除客户端记录
            del self.clients[client_id]
            logger.info(f"客户端记录已清理: {client_id}, 剩余客户端数: {len(self.clients)}")
    
    def on_subscribe_task(self, data):
        """
        订阅任务进度
        
        Args:
            data: 包含任务ID的字典
        """
        client_id = request.sid
        task_id = data.get('task_id')
        logger.info(f"收到任务订阅请求: client_id={client_id}, task_id={task_id}")
        
        if not task_id:
            logger.warning(f"无效的任务ID: {task_id}")
            emit('error', {'message': '无效的任务ID'})
            return
        
        # 获取任务
        task = task_manager.get_task(task_id)
        if not task:
            logger.warning(f"任务不存在: {task_id}")
            emit('error', {'message': '任务不存在'})
            return
        
        # 更新客户端记录
        self.clients[client_id]['task_id'] = task_id
        logger.info(f"已更新客户端任务关联: client_id={client_id}, task_id={task_id}")
        
        # 如果任务已完成，直接发送完成通知
        if task.status == TaskStatus.COMPLETED:
            logger.info(f"任务已完成，直接发送完成通知: task_id={task_id}")
            try:
                emit('transcription_completed', {
                    'task_id': task_id,
                    'text': task.result.get('text', ''),
                    'has_segments': len(task.result.get('segments', [])) > 0
                })
                logger.debug(f"完成通知已发送: task_id={task_id}")
            except Exception as e:
                logger.error(f"发送完成通知失败: task_id={task_id}, error={str(e)}")
            return
        
        # 如果任务已失败，直接发送错误通知
        if task.status == TaskStatus.ERROR:
            logger.info(f"任务已失败，直接发送错误通知: task_id={task_id}, error={task.error}")
            try:
                emit('transcription_error', {
                    'task_id': task_id,
                    'error': task.error
                })
                logger.debug(f"错误通知已发送: task_id={task_id}")
            except Exception as e:
                logger.error(f"发送错误通知失败: task_id={task_id}, error={str(e)}")
            return
        
        # 如果任务已取消，直接发送取消通知
        if task.status == TaskStatus.CANCELLED:
            logger.info(f"任务已取消，直接发送取消通知: task_id={task_id}")
            try:
                emit('transcription_cancelled', {
                    'task_id': task_id
                })
                logger.debug(f"取消通知已发送: task_id={task_id}")
            except Exception as e:
                logger.error(f"发送取消通知失败: task_id={task_id}, error={str(e)}")
            return
        
        # 启动进度监控线程
        if client_id not in self.progress_threads:
            logger.info(f"启动进度监控线程: client_id={client_id}, task_id={task_id}")
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
        try:
            emit('progress_update', {
                'task_id': task_id,
                'progress': task.progress,
                'message': task.message
            })
            logger.debug(f"初始进度已发送: task_id={task_id}, progress={task.progress}")
        except Exception as e:
            logger.error(f"发送初始进度失败: task_id={task_id}, error={str(e)}")
    
    def on_unsubscribe_task(self, data):
        """
        取消订阅任务进度
        
        Args:
            data: 包含任务ID的字典
        """
        client_id = request.sid
        logger.info(f"收到取消订阅请求: client_id={client_id}")
        
        # 停止进度线程
        if client_id in self.progress_threads:
            logger.debug(f"停止进度监控线程: client_id={client_id}")
            self.progress_threads[client_id]['stop'] = True
            del self.progress_threads[client_id]
        
        # 更新客户端记录
        if client_id in self.clients:
            old_task_id = self.clients[client_id].get('task_id')
            self.clients[client_id]['task_id'] = None
            logger.info(f"已清除客户端任务关联: client_id={client_id}, old_task_id={old_task_id}")
    
    def _monitor_progress(self, client_id, task_id):
        """
        监控任务进度
        
        Args:
            client_id: 客户端ID
            task_id: 任务ID
        """
        logger.info(f"开始监控任务进度: client_id={client_id}, task_id={task_id}")
        try:
            # 获取任务
            task = task_manager.get_task(task_id)
            if not task:
                logger.warning(f"任务不存在，停止监控: task_id={task_id}")
                return
            
            # 监控进度队列
            while client_id in self.clients and client_id in self.progress_threads:
                # 检查是否应该停止
                if self.progress_threads[client_id]['stop']:
                    logger.info(f"收到停止信号，结束监控: client_id={client_id}, task_id={task_id}")
                    break
                
                # 检查任务状态
                task = task_manager.get_task(task_id)
                if not task:
                    logger.warning(f"任务不存在，停止监控: task_id={task_id}")
                    break
                
                # 如果任务已完成，发送完成通知
                if task.status == TaskStatus.COMPLETED:
                    logger.info(f"任务完成，发送完成通知: task_id={task_id}")
                    try:
                        emit('transcription_completed', {
                            'task_id': task_id,
                            'text': task.result.get('text', ''),
                            'has_segments': len(task.result.get('segments', [])) > 0
                        }, namespace='/', to=client_id)
                        logger.debug(f"完成通知已发送: task_id={task_id}")
                    except Exception as e:
                        logger.error(f"发送完成通知失败: task_id={task_id}, error={str(e)}")
                    break
                
                # 如果任务已失败，发送错误通知
                if task.status == TaskStatus.ERROR:
                    logger.info(f"任务失败，发送错误通知: task_id={task_id}, error={task.error}")
                    try:
                        emit('transcription_error', {
                            'task_id': task_id,
                            'error': task.error
                        }, namespace='/', to=client_id)
                        logger.debug(f"错误通知已发送: task_id={task_id}")
                    except Exception as e:
                        logger.error(f"发送错误通知失败: task_id={task_id}, error={str(e)}")
                    break
                
                # 如果任务已取消，发送取消通知
                if task.status == TaskStatus.CANCELLED:
                    logger.info(f"任务取消，发送取消通知: task_id={task_id}")
                    try:
                        emit('transcription_cancelled', {
                            'task_id': task_id
                        }, namespace='/', to=client_id)
                        logger.debug(f"取消通知已发送: task_id={task_id}")
                    except Exception as e:
                        logger.error(f"发送取消通知失败: task_id={task_id}, error={str(e)}")
                    break
                
                # 尝试从队列获取进度更新
                try:
                    progress_data = task.progress_queue.get(timeout=0.5)
                    logger.debug(f"获取到进度更新: task_id={task_id}, progress={progress_data}")
                    try:
                        emit('progress_update', {
                            'task_id': task_id,
                            'progress': progress_data['progress'],
                            'message': progress_data['message']
                        }, namespace='/', to=client_id)
                        logger.debug(f"进度更新已发送: task_id={task_id}, progress={progress_data['progress']}")
                    except Exception as e:
                        logger.error(f"发送进度更新失败: task_id={task_id}, error={str(e)}")
                except queue.Empty:
                    # 队列为空，继续等待
                    pass
                
                # 短暂休眠，避免过度消耗CPU
                time.sleep(0.1)
        
        except Exception as e:
            logger.error(f"监控进度线程异常: client_id={client_id}, task_id={task_id}, error={str(e)}")
        
        finally:
            # 清理线程记录
            if client_id in self.progress_threads:
                del self.progress_threads[client_id]
                logger.info(f"进度监控线程已清理: client_id={client_id}, task_id={task_id}")


# 导出 WebSocket 命名空间
websocket_namespace = WebWhisperNamespace() 