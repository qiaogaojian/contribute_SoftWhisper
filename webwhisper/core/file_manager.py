"""
WebWhisper 文件管理模块
处理文件上传和存储
"""

import os
import time
from pathlib import Path
from werkzeug.utils import secure_filename

from webwhisper.utils.logging_utils import logger
from webwhisper.config import config


class FileManager:
    """文件管理类"""
    
    def __init__(self, upload_folder=None):
        """
        初始化文件管理器
        
        Args:
            upload_folder: 上传文件夹路径
        """
        self.upload_folder = upload_folder or config.get('upload_folder')
        os.makedirs(self.upload_folder, exist_ok=True)
    
    def allowed_file(self, filename):
        """
        检查文件是否允许上传
        
        Args:
            filename: 文件名
        
        Returns:
            bool: 是否允许
        """
        allowed_extensions = config.get('allowed_extensions')
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions
    
    def save_uploaded_file(self, file_obj):
        """
        保存上传的文件
        
        Args:
            file_obj: 文件对象
        
        Returns:
            dict: 包含文件信息的字典
        """
        if not file_obj:
            return {'success': False, 'error': '没有文件'}
        
        if file_obj.filename == '':
            return {'success': False, 'error': '没有选择文件'}
        
        if not self.allowed_file(file_obj.filename):
            return {'success': False, 'error': '不支持的文件类型'}
        
        try:
            # 安全处理文件名
            filename = secure_filename(file_obj.filename)
            
            # 添加时间戳避免文件名冲突
            base_name, ext = os.path.splitext(filename)
            timestamp = int(time.time())
            filename = f"{base_name}_{timestamp}{ext}"
            
            # 保存文件
            file_path = os.path.join(self.upload_folder, filename)
            file_obj.save(file_path)
            
            # 创建任务ID
            task_id = str(timestamp)
            
            logger.info(f"文件已上传: {file_path}, 任务ID: {task_id}")
            
            return {
                'success': True,
                'filename': filename,
                'task_id': task_id,
                'file_path': file_path
            }
        
        except Exception as e:
            logger.error(f"保存文件失败: {str(e)}")
            return {'success': False, 'error': f'保存文件失败: {str(e)}'}
    
    def get_file_path(self, filename):
        """
        获取文件路径
        
        Args:
            filename: 文件名
        
        Returns:
            str: 文件路径
        """
        return os.path.join(self.upload_folder, filename)
    
    def file_exists(self, filename):
        """
        检查文件是否存在
        
        Args:
            filename: 文件名
        
        Returns:
            bool: 是否存在
        """
        return os.path.exists(self.get_file_path(filename))
    
    def delete_file(self, filename):
        """
        删除文件
        
        Args:
            filename: 文件名
        
        Returns:
            bool: 是否成功
        """
        try:
            file_path = self.get_file_path(filename)
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"文件已删除: {file_path}")
                return True
            return False
        except Exception as e:
            logger.error(f"删除文件失败: {str(e)}")
            return False
    
    def clean_old_files(self, max_age_hours=24):
        """
        清理旧文件
        
        Args:
            max_age_hours: 最大保留时间（小时）
        
        Returns:
            int: 删除的文件数量
        """
        try:
            count = 0
            now = time.time()
            max_age_seconds = max_age_hours * 3600
            
            for filename in os.listdir(self.upload_folder):
                file_path = os.path.join(self.upload_folder, filename)
                if os.path.isfile(file_path):
                    file_age = now - os.path.getmtime(file_path)
                    if file_age > max_age_seconds:
                        os.remove(file_path)
                        count += 1
                        logger.info(f"已清理旧文件: {file_path}")
            
            return count
        
        except Exception as e:
            logger.error(f"清理旧文件失败: {str(e)}")
            return 0


# 导出文件管理器实例
file_manager = FileManager() 