"""
WebWhisper 转录器模块
处理转录业务逻辑
"""

import os
from pathlib import Path

from webwhisper.utils.logging_utils import logger
from webwhisper.utils.whisper_utils import transcribe_audio
from webwhisper.utils.subtitle_utils import whisper_to_srt, segments_to_srt, save_srt
from webwhisper.core.task_manager import task_manager
from webwhisper.config import config
from pycore.utils.file_utils import FileUtils


class Transcriber:
    """转录器类"""
    
    def __init__(self):
        """初始化转录器"""
        self.task_manager = task_manager
    
    def create_transcription_task(self, file_path, options):
        """
        创建转录任务
        
        Args:
            file_path: 文件路径
            options: 转录选项
        
        Returns:
            dict: 包含任务ID的字典
        """
        try:
            # 从options中获取task_id
            task_id = options.get('task_id')
            
            # 创建任务
            task = self.task_manager.create_task(file_path, options, task_id)
            
            return {
                'success': True,
                'task_id': task.task_id
            }
        except Exception as e:
            logger.error(f"创建转录任务失败: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def start_transcription(self, task_id):
        """
        开始转录
        
        Args:
            task_id: 任务ID
        
        Returns:
            dict: 结果信息
        """
        # 启动任务
        success = task_manager.start_task(task_id)
        
        if not success:
            task = task_manager.get_task(task_id)
            if not task:
                return {'success': False, 'error': '任务不存在'}
            
            return {'success': False, 'error': '任务无法启动'}
        
        return {'success': True, 'task_id': task_id}
    
    def cancel_transcription(self, task_id):
        """
        取消转录
        
        Args:
            task_id: 任务ID
        
        Returns:
            dict: 结果信息
        """
        # 取消任务
        success = task_manager.cancel_task(task_id)
        
        if not success:
            return {'success': False, 'error': '任务无法取消'}
        
        return {'success': True}
    
    def get_transcription_result(self, task_id):
        """
        获取转录结果
        
        Args:
            task_id: 任务ID
        
        Returns:
            dict: 结果信息
        """
        return task_manager.get_task_result(task_id)
    
    def get_transcription_status(self, task_id):
        """
        获取转录状态
        
        Args:
            task_id: 任务ID
        
        Returns:
            dict: 状态信息
        """
        return task_manager.get_task_status(task_id)
    
    def generate_srt(self, task_id, output_path=None):
        """
        生成SRT字幕文件
        
        Args:
            task_id: 任务ID
            output_path: 输出路径
        
        Returns:
            dict: 结果信息
        """
        # 获取任务
        task = task_manager.get_task(task_id)
        if not task:
            return {'success': False, 'error': '任务不存在'}
        
        # 检查任务是否完成
        if task.status != 'completed':
            return {'success': False, 'error': '转录尚未完成'}
        
        try:
            # 生成SRT内容
            if task.result.get('segments'):
                # 使用分段数据生成SRT
                srt_content = segments_to_srt(task.result.get('segments', []))
            else:
                # 使用原始Whisper输出生成SRT
                whisper_output = task.result.get('text', '')
                srt_content = whisper_to_srt(whisper_output)
            
            # 如果没有指定输出路径，使用默认路径
            if not output_path:
                file_path = task.file_path
                filename = os.path.splitext(os.path.basename(file_path))[0] + '.srt'
                output_path = os.path.join(config.get('upload_folder'), filename)
            
            # 保存SRT文件
            success = save_srt(srt_content, output_path)
            
            if success:
                return {
                    'success': True,
                    'filename': os.path.basename(output_path),
                    'path': output_path
                }
            else:
                return {'success': False, 'error': '保存SRT文件失败'}
        
        except Exception as e:
            logger.error(f"生成SRT文件失败: {str(e)}")
            return {'success': False, 'error': f'生成SRT文件失败: {str(e)}'}


# 导出转录器实例
transcriber = Transcriber() 