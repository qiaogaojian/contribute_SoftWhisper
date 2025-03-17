"""
WebWhisper WebSocket 模块
处理实时通信
"""

import threading
import time
import queue
from flask_socketio import Namespace, emit
from flask import request, current_app

from webwhisper.utils.logging_utils import logger
from webwhisper.core.task_manager import task_manager
from webwhisper.models.task import TaskStatus


# 导入全局socketio实例
from flask import current_app

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
        self.task_monitor_thread = None  # 任务监控线程
        self.stop_monitoring = False  # 停止监控标志
        self.app = None  # Flask应用实例
        self.socketio = None  # SocketIO实例
        logger.info(f"WebSocket 命名空间已初始化: {namespace}")
        
        # 不在初始化时启动全局任务监控线程，等待init_app调用
    
    def init_app(self, socketio, app):
        """
        初始化WebSocket命名空间
        
        Args:
            socketio: SocketIO实例
            app: Flask应用实例
        """
        self.socketio = socketio
        self.app = app
        
        # 注册命名空间
        socketio.on_namespace(self)
        
        # 启动全局任务监控线程
        self._start_task_monitor()
        
        logger.info(f"WebSocket命名空间已初始化: {self.namespace}")
    
    def _start_task_monitor(self):
        """启动全局任务监控线程"""
        if self.task_monitor_thread is None or not self.task_monitor_thread.is_alive():
            self.stop_monitoring = False
            self.task_monitor_thread = threading.Thread(
                target=self._monitor_all_tasks
            )
            self.task_monitor_thread.daemon = True
            self.task_monitor_thread.start()
            logger.info("全局任务监控线程已启动")
    
    def _monitor_all_tasks(self):
        """监控所有任务的状态变化"""
        logger.info("开始监控所有任务")
        
        last_task_statuses = {}  # 上次任务状态
        
        while not self.stop_monitoring:
            try:
                # 创建应用上下文
                if self.app:
                    with self.app.app_context():
                        # 获取所有任务
                        tasks = task_manager.get_all_tasks()
                        
                        # 检查每个任务的状态
                        for task_id, task in tasks.items():
                            # 如果任务状态发生变化，记录并广播
                            if task_id not in last_task_statuses or last_task_statuses[task_id] != task.status:
                                logger.info(f"任务状态变化: task_id={task_id}, status={task.status}, progress={task.progress}")
                                last_task_statuses[task_id] = task.status
                                
                                # 如果任务完成，广播完成通知
                                if task.status == TaskStatus.COMPLETED:
                                    logger.info(f"任务完成，广播完成通知: task_id={task_id}")
                                    try:
                                        if self.socketio:
                                            self.socketio.emit('transcription_completed', {
                                                'task_id': task_id,
                                                'text': task.result.get('text', ''),
                                                'has_segments': len(task.result.get('segments', [])) > 0
                                            }, namespace='/')
                                            logger.debug(f"完成通知已广播: task_id={task_id}")
                                        else:
                                            logger.warning(f"socketio实例为None，无法广播完成通知: task_id={task_id}")
                                    except Exception as e:
                                        logger.error(f"广播完成通知失败: task_id={task_id}, error={str(e)}")
                                
                                # 如果任务失败，广播错误通知
                                elif task.status == TaskStatus.ERROR:
                                    logger.info(f"任务失败，广播错误通知: task_id={task_id}, error={task.error}")
                                    try:
                                        if self.socketio:
                                            self.socketio.emit('transcription_error', {
                                                'task_id': task_id,
                                                'error': task.error
                                            }, namespace='/')
                                            logger.debug(f"错误通知已广播: task_id={task_id}")
                                        else:
                                            logger.warning(f"socketio实例为None，无法广播错误通知: task_id={task_id}")
                                    except Exception as e:
                                        logger.error(f"广播错误通知失败: task_id={task_id}, error={str(e)}")
                                
                                # 如果任务取消，广播取消通知
                                elif task.status == TaskStatus.CANCELLED:
                                    logger.info(f"任务取消，广播取消通知: task_id={task_id}")
                                    try:
                                        if self.socketio:
                                            self.socketio.emit('transcription_cancelled', {
                                                'task_id': task_id
                                            }, namespace='/')
                                            logger.debug(f"取消通知已广播: task_id={task_id}")
                                        else:
                                            logger.warning(f"socketio实例为None，无法广播取消通知: task_id={task_id}")
                                    except Exception as e:
                                        logger.error(f"广播取消通知失败: task_id={task_id}, error={str(e)}")
                            
                            # 如果任务正在进行中，检查进度队列并广播进度
                            if task.status == TaskStatus.RUNNING:
                                try:
                                    # 非阻塞方式获取进度
                                    try:
                                        progress_data = task.progress_queue.get_nowait()
                                        logger.debug(f"获取到进度更新: task_id={task_id}, progress={progress_data}")
                                        try:
                                            if self.socketio:
                                                self.socketio.emit('progress_update', {
                                                    'task_id': task_id,
                                                    'progress': progress_data['progress'],
                                                    'message': progress_data['message']
                                                }, namespace='/')
                                                logger.debug(f"进度更新已广播: task_id={task_id}, progress={progress_data['progress']}")
                                            else:
                                                logger.warning(f"socketio实例为None，无法广播进度更新: task_id={task_id}")
                                        except Exception as e:
                                            logger.error(f"广播进度更新失败: task_id={task_id}, error={str(e)}")
                                    except queue.Empty:
                                        # 队列为空，继续检查下一个任务
                                        pass
                                except Exception as e:
                                    logger.error(f"检查任务进度失败: task_id={task_id}, error={str(e)}")
                else:
                    logger.warning("应用实例未设置，无法创建应用上下文")
                
                # 短暂休眠，避免过度消耗CPU
                time.sleep(0.5)
            
            except Exception as e:
                logger.error(f"全局任务监控线程异常: {str(e)}")
                time.sleep(1)  # 出错后稍微延长休眠时间
    
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
        
        # 发送连接响应
        if self.socketio:
            self.socketio.emit('connect_response', {'status': 'connected', 'client_id': client_id}, room=client_id)
        else:
            emit('connect_response', {'status': 'connected', 'client_id': client_id})
        
        # 确保全局任务监控线程正在运行
        if self.task_monitor_thread is None or not self.task_monitor_thread.is_alive():
            logger.warning("全局任务监控线程不在运行状态，重新启动")
            self._start_task_monitor()
    
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
            
            # 如果没有客户端连接，可以考虑停止全局监控线程
            if not self.clients and self.task_monitor_thread is not None:
                logger.info("没有客户端连接，停止全局任务监控线程")
                self.stop_monitoring = True
                self.task_monitor_thread = None
    
    def on_subscribe_task(self, data):
        """
        订阅任务进度
        
        Args:
            data: 包含任务ID的字典
        """
        try:
            client_id = request.sid
            task_id = data.get('task_id')
            logger.info(f"收到任务订阅请求: client_id={client_id}, task_id={task_id}, data={data}")
            
            if not task_id:
                logger.warning(f"无效的任务ID: {task_id}")
                if self.socketio:
                    self.socketio.emit('error', {'message': '无效的任务ID'}, room=client_id)
                else:
                    emit('error', {'message': '无效的任务ID'})
                return
            
            # 获取任务
            task = task_manager.get_task(task_id)
            if not task:
                logger.warning(f"任务不存在: {task_id}")
                if self.socketio:
                    self.socketio.emit('error', {'message': '任务不存在'}, room=client_id)
                else:
                    emit('error', {'message': '任务不存在'})
                return
            
            # 更新客户端记录
            self.clients[client_id]['task_id'] = task_id
            logger.info(f"已更新客户端任务关联: client_id={client_id}, task_id={task_id}")
            
            # 如果任务已完成，直接发送完成通知
            if task.status == TaskStatus.COMPLETED:
                logger.info(f"任务已完成，直接发送完成通知: task_id={task_id}")
                try:
                    if self.socketio:
                        self.socketio.emit('transcription_completed', {
                            'task_id': task_id,
                            'text': task.result.get('text', ''),
                            'has_segments': len(task.result.get('segments', [])) > 0
                        }, room=client_id)
                    else:
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
                    if self.socketio:
                        self.socketio.emit('transcription_error', {
                            'task_id': task_id,
                            'error': task.error
                        }, room=client_id)
                    else:
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
                    if self.socketio:
                        self.socketio.emit('transcription_cancelled', {
                            'task_id': task_id
                        }, room=client_id)
                    else:
                        emit('transcription_cancelled', {
                            'task_id': task_id
                        })
                    logger.debug(f"取消通知已发送: task_id={task_id}")
                except Exception as e:
                    logger.error(f"发送取消通知失败: task_id={task_id}, error={str(e)}")
                return
            
            # 发送当前进度
            try:
                if self.socketio:
                    self.socketio.emit('progress_update', {
                        'task_id': task_id,
                        'progress': task.progress,
                        'message': task.message
                    }, room=client_id)
                else:
                    emit('progress_update', {
                        'task_id': task_id,
                        'progress': task.progress,
                        'message': task.message
                    })
                logger.debug(f"初始进度已发送: task_id={task_id}, progress={task.progress}")
            except Exception as e:
                logger.error(f"发送初始进度失败: task_id={task_id}, error={str(e)}")
            
            # 发送订阅确认
            try:
                if self.socketio:
                    self.socketio.emit('subscription_confirmed', {'task_id': task_id}, room=client_id)
                else:
                    emit('subscription_confirmed', {'task_id': task_id})
                logger.info(f"订阅确认已发送: client_id={client_id}, task_id={task_id}")
            except Exception as e:
                logger.error(f"发送订阅确认失败: client_id={client_id}, task_id={task_id}, error={str(e)}")
        
        except Exception as e:
            logger.error(f"处理订阅请求时发生错误: client_id={request.sid}, error={str(e)}")
            try:
                if self.socketio:
                    self.socketio.emit('error', {'message': '订阅失败，请重试'}, room=request.sid)
                else:
                    emit('error', {'message': '订阅失败，请重试'})
            except Exception as e2:
                logger.error(f"发送错误通知失败: error={str(e2)}")
    
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
            
            logger.info(f"任务初始状态: task_id={task_id}, status={task.status}, progress={task.progress}")
            
            # 监控进度队列
            poll_count = 0
            last_progress = -1
            
            while client_id in self.clients and client_id in self.progress_threads:
                poll_count += 1
                
                # 每10次轮询记录一次日志
                if poll_count % 10 == 0:
                    logger.debug(f"进度监控轮询中: client_id={client_id}, task_id={task_id}, poll_count={poll_count}")
                
                # 检查是否应该停止
                if self.progress_threads[client_id]['stop']:
                    logger.info(f"收到停止信号，结束监控: client_id={client_id}, task_id={task_id}")
                    break
                
                # 检查任务状态
                task = task_manager.get_task(task_id)
                if not task:
                    logger.warning(f"任务不存在，停止监控: task_id={task_id}")
                    break
                
                # 如果进度有变化，记录日志
                if task.progress != last_progress:
                    logger.info(f"任务进度更新: task_id={task_id}, status={task.status}, progress={task.progress}, message={task.message}")
                    last_progress = task.progress
                
                # 在应用上下文中执行
                if self.app:
                    with self.app.app_context():
                        # 如果任务已完成，发送完成通知
                        if task.status == TaskStatus.COMPLETED:
                            logger.info(f"任务完成，发送完成通知: task_id={task_id}")
                            try:
                                if self.socketio:
                                    self.socketio.emit('transcription_completed', {
                                        'task_id': task_id,
                                        'text': task.result.get('text', ''),
                                        'has_segments': len(task.result.get('segments', [])) > 0
                                    }, namespace='/', room=client_id)
                                    logger.debug(f"完成通知已发送: task_id={task_id}")
                                else:
                                    logger.warning(f"socketio实例为None，无法发送完成通知: task_id={task_id}")
                            except Exception as e:
                                logger.error(f"发送完成通知失败: task_id={task_id}, error={str(e)}")
                            break
                        
                        # 如果任务已失败，发送错误通知
                        if task.status == TaskStatus.ERROR:
                            logger.info(f"任务失败，发送错误通知: task_id={task_id}, error={task.error}")
                            try:
                                if self.socketio:
                                    self.socketio.emit('transcription_error', {
                                        'task_id': task_id,
                                        'error': task.error
                                    }, namespace='/', room=client_id)
                                    logger.debug(f"错误通知已发送: task_id={task_id}")
                                else:
                                    logger.warning(f"socketio实例为None，无法发送错误通知: task_id={task_id}")
                            except Exception as e:
                                logger.error(f"发送错误通知失败: task_id={task_id}, error={str(e)}")
                            break
                        
                        # 如果任务已取消，发送取消通知
                        if task.status == TaskStatus.CANCELLED:
                            logger.info(f"任务取消，发送取消通知: task_id={task_id}")
                            try:
                                if self.socketio:
                                    self.socketio.emit('transcription_cancelled', {
                                        'task_id': task_id
                                    }, namespace='/', room=client_id)
                                    logger.debug(f"取消通知已发送: task_id={task_id}")
                                else:
                                    logger.warning(f"socketio实例为None，无法发送取消通知: task_id={task_id}")
                            except Exception as e:
                                logger.error(f"发送取消通知失败: task_id={task_id}, error={str(e)}")
                            break
                        
                        # 尝试从队列获取进度更新
                        try:
                            progress_data = task.progress_queue.get(timeout=0.5)
                            logger.debug(f"获取到进度更新: task_id={task_id}, progress={progress_data}")
                            try:
                                if self.socketio:
                                    self.socketio.emit('progress_update', {
                                        'task_id': task_id,
                                        'progress': progress_data['progress'],
                                        'message': progress_data['message']
                                    }, namespace='/', room=client_id)
                                    logger.debug(f"进度更新已发送: task_id={task_id}, progress={progress_data['progress']}")
                                else:
                                    logger.warning(f"socketio实例为None，无法发送进度更新: task_id={task_id}")
                            except Exception as e:
                                logger.error(f"发送进度更新失败: task_id={task_id}, error={str(e)}")
                        except queue.Empty:
                            # 队列为空，继续等待
                            pass
                else:
                    logger.warning(f"应用实例未设置，无法创建应用上下文: client_id={client_id}, task_id={task_id}")
                
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