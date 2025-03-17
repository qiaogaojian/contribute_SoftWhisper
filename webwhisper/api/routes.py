"""
WebWhisper API 路由模块
处理 HTTP 请求
"""

from flask import Blueprint, request, jsonify, send_from_directory, session

from webwhisper.core.file_manager import file_manager
from webwhisper.core.transcriber import transcriber
from webwhisper.utils.logging_utils import logger
from webwhisper.config import config
from webwhisper.core.task_manager import task_manager

# 创建蓝图
api = Blueprint('api', __name__)


@api.route('/upload', methods=['POST'])
def upload_file():
    """处理文件上传"""
    if 'file' not in request.files:
        return jsonify({'error': '没有文件'}), 400
    
    file = request.files['file']
    result = file_manager.save_uploaded_file(file)
    
    if not result['success']:
        return jsonify({'error': result['error']}), 400
    
    # 保存文件路径到会话
    session['current_task_id'] = result['task_id']
    session['current_file_path'] = result['file_path']
    
    # 确保会话数据被保存
    session.modified = True
    
    return jsonify(result)


@api.route('/transcribe', methods=['POST'])
def transcribe():
    """处理转录请求"""
    try:
        # 获取会话中的文件路径和任务ID
        file_path = session.get('current_file_path')
        task_id = session.get('current_task_id')
        
        if not file_path or not task_id:
            return jsonify({'success': False, 'error': '请先上传文件'})
        
        # 获取请求参数
        data = request.get_json()
        options = {
            'task_id': task_id,  # 使用session中的task_id
            'model': data.get('model', 'base'),
            'task': data.get('task', 'transcribe'),
            'language': data.get('language', 'auto'),
            'beam_size': int(data.get('beam_size', 5)),
            'start_time': data.get('start_time'),
            'end_time': data.get('end_time'),
            'generate_srt': data.get('generate_srt', False),
            'whisper_executable': data.get('whisper_path', config.get('whisper_executable'))
        }
        
        logger.info(f"转录请求: task_id={task_id}, file_path={file_path}, session={session}")
        
        # 创建转录任务
        result = transcriber.create_transcription_task(file_path, options)
        
        if result['success']:
            # 启动转录
            transcriber.start_transcription(result['task_id'])
            return jsonify({'success': True, 'task_id': result['task_id']})
        else:
            return jsonify({'success': False, 'error': result['error']})
            
    except Exception as e:
        logger.error(f"处理转录请求失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@api.route('/cancel_transcription', methods=['POST'])
def cancel_transcription():
    """取消转录任务"""
    data = request.json
    task_id = data.get('task_id')
    
    result = transcriber.cancel_transcription(task_id)
    
    if not result['success']:
        return jsonify({'error': '任务不存在或无法取消'}), 404
    
    return jsonify({'success': True})


@api.route('/get_result', methods=['GET'])
def get_result():
    """获取转录结果"""
    task_id = request.args.get('task_id')
    
    result = transcriber.get_transcription_result(task_id)
    
    if not result.get('success', True):
        return jsonify(result), 404
    
    return jsonify(result)


@api.route('/download_srt', methods=['POST'])
def download_srt():
    """下载SRT字幕文件"""
    data = request.json
    task_id = data.get('task_id')
    
    result = transcriber.generate_srt(task_id)
    
    if not result['success']:
        return jsonify(result), 400
    
    return jsonify(result)


@api.route('/download/<filename>')
def download_file(filename):
    """下载文件"""
    return send_from_directory(config.get('upload_folder'), filename, as_attachment=True)


@api.route('/save_config', methods=['POST'])
def update_config():
    """保存配置"""
    data = request.json
    
    if 'beam_size' in data:
        config.set('beam_size', int(data['beam_size']))
    
    if 'whisper_path' in data:
        config.set('whisper_executable', data['whisper_path'])
    
    config.save()
    return jsonify({'success': True}) 