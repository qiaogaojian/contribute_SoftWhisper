"""
WebWhisper API 路由模块
处理 HTTP 请求
"""

from flask import Blueprint, request, jsonify, send_from_directory, session

from webwhisper.core.file_manager import file_manager
from webwhisper.core.transcriber import transcriber
from webwhisper.utils.logging_utils import logger
from webwhisper.config import config

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
def start_transcription():
    """开始转录任务"""
    data = request.json
    task_id = data.get('task_id')
    file_path = data.get('file_path') or session.get('current_file_path')
    
    logger.info(f"转录请求: task_id={task_id}, file_path={file_path}, session={session}")
    
    if not task_id:
        return jsonify({'error': '无效的任务ID'}), 400
    
    if not file_path:
        # 尝试从任务ID推断文件路径
        import os
        import time
        upload_folder = config.get('upload_folder')
        for filename in os.listdir(upload_folder):
            full_path = os.path.join(upload_folder, filename)
            if os.path.isfile(full_path) and os.path.getmtime(full_path) > time.time() - 300:  # 5分钟内上传的文件
                file_path = full_path
                session['current_file_path'] = file_path
                logger.info(f"从最近上传的文件推断文件路径: {file_path}")
                break
    
    if not file_path:
        return jsonify({'error': '无效的文件路径，请重新上传文件'}), 400
    
    # 转录选项
    options = {
        'model_name': data.get('model', 'base'),
        'task': data.get('task', 'transcribe'),
        'language': data.get('language', 'auto'),
        'beam_size': int(data.get('beam_size', 5)),
        'start_time': data.get('start_time', '00:00:00'),
        'end_time': data.get('end_time', ''),
        'generate_srt': data.get('generate_srt', False),
        'whisper_executable': data.get('whisper_path', config.get('whisper_executable'))
    }
    
    # 创建转录任务
    result = transcriber.create_transcription_task(file_path, options)
    
    if not result['success']:
        return jsonify(result), 400
    
    # 启动转录
    start_result = transcriber.start_transcription(result['task_id'])
    
    if not start_result['success']:
        return jsonify(start_result), 400
    
    return jsonify({
        'success': True,
        'task_id': result['task_id']
    })


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