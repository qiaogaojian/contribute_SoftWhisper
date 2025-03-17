"""
WebWhisper - Web 版本的 SoftWhisper 音频/视频转录应用
基于 Whisper.cpp 实现
"""

import os
import sys
import json
import queue
import threading
import tempfile
import time
import re
import urllib.request
import subprocess
from flask import Flask, render_template, request, jsonify, send_from_directory, session
from flask_socketio import SocketIO
import psutil
from werkzeug.utils import secure_filename

# 调试辅助函数
def debug_print(msg):
    sys.__stdout__.write(f"DEBUG: {msg}\n")
    sys.__stdout__.flush()

def get_default_whisper_cpp_path():
    program_dir = os.path.dirname(os.path.abspath(__file__))
    if os.name == "nt":
        # Windows 路径
        return os.path.join(program_dir, "Whisper_win-x64")
    else:
        # Linux 路径
        return os.path.join(program_dir, "Whisper_linux-x64")

# 配置文件
CONFIG_FILE = 'web_config.json'

# 创建 Flask 应用
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB 最大上传限制
socketio = SocketIO(app)

# 确保上传目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# 全局变量
transcription_tasks = {}  # 存储转录任务信息
progress_queues = {}      # 存储进度队列

# 允许的文件扩展名
ALLOWED_EXTENSIONS = {'wav', 'mp3', 'm4a', 'flac', 'ogg', 'wma', 'mp4', 'mov', 'avi', 'mkv'}

# 允许的模型文件名
ALLOWED_MODELS = [
    "ggml-tiny.bin", "ggml-tiny.en.bin",
    "ggml-base.bin", "ggml-base.en.bin",
    "ggml-small.bin", "ggml-small.en.bin",
    "ggml-medium.bin", "ggml-medium.en.bin",
    "ggml-large.bin", "ggml-large-v2.bin",
    "ggml-large-v3.bin", "ggml-large-v3-turbo.bin"
]

# 导入字幕处理模块
try:
    from subtitles import whisper_to_srt, save_whisper_as_srt
except ImportError:
    debug_print("无法导入字幕处理模块，将使用内部实现")
    
    def whisper_to_srt(whisper_output):
        """
        将 Whisper 输出转换为 SRT 格式
        """
        lines = whisper_output.strip().split('\n')
        srt_parts = []
        
        counter = 1
        for line in lines:
            match = re.match(r'\[(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})\] (.*)', line.strip())
            if match:
                start_time, end_time, text = match.groups()
                
                # 将点转换为逗号
                start_time = start_time.replace('.', ',')
                end_time = end_time.replace('.', ',')
                
                # 格式化为 SRT 条目
                srt_parts.append(f"{counter}")
                srt_parts.append(f"{start_time} --> {end_time}")
                srt_parts.append(f"{text}")
                srt_parts.append("")  # 空行
                
                counter += 1
        
        return "\n".join(srt_parts)

# 导入转录功能
try:
    from SoftWhisper import transcribe_audio
except ImportError:
    debug_print("无法导入 SoftWhisper 转录功能，将使用内部实现")
    
    # 这里实现一个简化版的 transcribe_audio 函数
    def transcribe_audio(file_path, options, progress_callback=None, stop_event=None):
        """
        使用 Whisper.cpp 进行转录
        """
        debug_print(f"转录文件: {file_path}")
        model_name = options.get('model_name', 'base')
        model_path = os.path.join("models", "whisper", f"ggml-{model_name}.bin")
        language = options.get('language', 'auto')
        beam_size = min(int(options.get('beam_size', 5)), 8)
        task = options.get('task', 'transcribe')
        
        # 构建 whisper-cli 命令
        executable = options.get('whisper_executable')
        cmd = [
            executable,
            "-m", model_path,
            "-f", file_path,
            "-bs", str(beam_size),
            "-pp",  # 实时进度
            "-l", language
        ]
        # 如果用户想要翻译为英文
        if task == "translate":
            cmd.append("-translate")
        
        # 始终使用带时间戳的 JSON 输出
        cmd.append("-oj")
        
        debug_print(f"运行 Whisper.cpp 命令: {' '.join(cmd)}")
        
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        
        process = None
        stdout_lines = []
        stderr_data = []
        cancelled = False
        
        try:
            # 确保编码为 utf-8，以正确捕获重音字符
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=env,
                encoding='utf-8'
            )
            
            process_id = process.pid
            debug_print(f"Whisper.cpp 进程已启动 (PID {process_id})。")
            
            # 在单独的线程上读取 stderr，这样它就不会阻塞
            def read_stderr():
                for line in iter(process.stderr.readline, ''):
                    if stop_event and stop_event.is_set():
                        return
                    stderr_data.append(line)
            
            stderr_thread = threading.Thread(target=read_stderr, daemon=True)
            stderr_thread.start()
            
            # 时间戳行的简化模式
            timestamp_pattern = (
                r'\[(\d{2}:\d{2}:\d{2}\.\d{3}) --> '      # group(1) 开始时间
                r'(\d{2}:\d{2}:\d{2}\.\d{3})\]'            # group(2) 结束时间
                r' (.*)'                                   # group(3) 文本
            )
            
            # 持续读取 stdout 以获取进度行
            while process.poll() is None:
                if stop_event and stop_event.is_set():
                    debug_print("停止事件已触发。终止 Whisper.cpp 进程...")
                    
                    # 在 Windows 或 *nix 上终止
                    try:
                        import psutil
                        parent = psutil.Process(process_id)
                        for child in parent.children(recursive=True):
                            child.kill()
                        parent.kill()
                    except psutil.NoSuchProcess:
                        pass
                    except Exception as e:
                        debug_print(f"终止进程时出错: {e}")
                    
                    cancelled = True
                    break
                
                line = process.stdout.readline()
                if line:
                    stdout_lines.append(line)
                    # 尝试从时间戳解析进度
                    match_for_progress = re.search(
                        r'\[(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})\]',
                        line.strip()
                    )
                    if match_for_progress:
                        start_str = match_for_progress.group(1)
                        try:
                            h, m, s_milli = start_str.split(':')
                            s, ms = s_milli.split('.')
                            current_time = (int(h) * 3600 + int(m) * 60 + int(s)) + (float(ms) / 1000.0)
                            progress = int((current_time / 100.0) * 100)  # 假设音频长度为100秒
                            if progress_callback:
                                progress_callback(progress, f"转录中: {progress}% 完成")
                        except Exception as e:
                            debug_print(f"解析进度时出错: {e}")
                else:
                    time.sleep(0.1)
            
            # 处理剩余的 stdout
            for line in process.stdout:
                stdout_lines.append(line)
            
            # 等待 stderr 完成
            stderr_thread.join(timeout=1.0)
        
        except Exception as e:
            debug_print(f"转录过程中出错: {e}")
            if process and process.poll() is None:
                process.terminate()
                time.sleep(0.1)
                if process.poll() is None:
                    process.kill()
            
            return {
                'text': f"转录过程中出错: {str(e)}",
                'segments': [],
                'stderr': ''.join(stderr_data),
                'cancelled': True
            }
        
        finally:
            # 如果仍在运行，杀死它
            if process and process.poll() is None:
                process.terminate()
                time.sleep(0.1)
                if process.poll() is None:
                    process.kill()
        
        # 如果取消，清理并退出
        if cancelled or (stop_event and stop_event.is_set()):
            if progress_callback:
                progress_callback(0, "转录已取消")
            
            return {
                'text': "转录已被用户取消。",
                'segments': [],
                'stderr': ''.join(stderr_data),
                'cancelled': True
            }
        
        # 解析最终文本
        if progress_callback:
            progress_callback(90, "处理转录结果...")
        
        output_text = "".join(stdout_lines).strip()
        segments = []
        full_text = ""
        
        # 从 whisper 输出解析段
        for line in output_text.split('\n'):
            line = line.strip()
            match = re.search(timestamp_pattern, line)
            if match:
                start_str = match.group(1)
                end_str   = match.group(2)
                text_str  = match.group(3).strip() if match.group(3) else ""
                
                # 将 HH:MM:SS.mmm 格式的开始/结束时间转换为秒
                try:
                    h1, m1, s1ms = start_str.split(':')
                    s1, ms1 = s1ms.split('.')
                    stime = int(h1)*3600 + int(m1)*60 + int(s1) + float(ms1)/1000
                    
                    h2, m2, s2ms = end_str.split(':')
                    s2, ms2 = s2ms.split('.')
                    etime = int(h2)*3600 + int(m2)*60 + int(s2) + float(ms2)/1000
                except:
                    stime, etime = 0.0, 0.0
                
                seg_data = {
                    "start": stime,
                    "end":   etime,
                    "text":  text_str
                }
                segments.append(seg_data)
                
                if full_text:
                    full_text += " " + text_str
                else:
                    full_text = text_str
        
        # 如果没有带时间戳的段，将整个输出视为文本
        if not segments:
            full_text = output_text
            segments.append({
                "start": 0.0,
                "end": 100.0,  # 假设音频长度为100秒
                "text": full_text
            })
        
        if progress_callback:
            progress_callback(100, "转录成功完成")
        
        return {
            'text': output_text,  # 返回带时间戳的原始 Whisper 输出
            'segments': segments,
            'stderr': ''.join(stderr_data),
            'cancelled': False
        }

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def load_config():
    """加载配置文件"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            debug_print(f"加载配置文件出错: {e}")
    return {
        'beam_size': 5,
        'WHISPER_CPP_PATH': get_default_whisper_cpp_path()
    }

def save_config(config):
    """保存配置文件"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        debug_print("配置已保存")
    except Exception as e:
        debug_print(f"保存配置文件出错: {e}")

@app.route('/')
def index():
    """主页"""
    config = load_config()
    return render_template('index.html', 
                          models=ALLOWED_MODELS,
                          config=config)

@app.route('/upload', methods=['POST'])
def upload_file():
    """处理文件上传"""
    if 'file' not in request.files:
        return jsonify({'error': '没有文件'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '没有选择文件'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # 创建任务ID
        task_id = str(int(time.time()))
        session['current_task_id'] = task_id
        session['current_file_path'] = file_path
        
        return jsonify({
            'success': True,
            'filename': filename,
            'task_id': task_id
        })
    
    return jsonify({'error': '不支持的文件类型'}), 400

@app.route('/transcribe', methods=['POST'])
def start_transcription():
    """开始转录任务"""
    data = request.json
    task_id = data.get('task_id')
    file_path = session.get('current_file_path')
    
    if not task_id or not file_path:
        return jsonify({'error': '无效的任务或文件'}), 400
    
    # 转录选项
    options = {
        'model_name': data.get('model', 'base'),
        'task': data.get('task', 'transcribe'),
        'language': data.get('language', 'auto'),
        'beam_size': int(data.get('beam_size', 5)),
        'start_time': data.get('start_time', '00:00:00'),
        'end_time': data.get('end_time', ''),
        'generate_srt': data.get('generate_srt', False),
        'whisper_executable': data.get('whisper_path', get_default_whisper_cpp_path())
    }
    
    # 如果用户选择了目录，猜测实际的二进制文件名
    exe_path = options['whisper_executable']
    if os.path.isdir(exe_path):
        if os.name == "nt":
            exe_path = os.path.join(exe_path, "whisper-cli.exe")
        else:
            exe_path = os.path.join(exe_path, "whisper-cli")
        options['whisper_executable'] = exe_path
    
    # 创建进度队列
    progress_queue = queue.Queue()
    progress_queues[task_id] = progress_queue
    
    # 创建停止事件
    stop_event = threading.Event()
    
    # 存储任务信息
    transcription_tasks[task_id] = {
        'file_path': file_path,
        'options': options,
        'progress_queue': progress_queue,
        'stop_event': stop_event,
        'status': 'running'
    }
    
    # 启动转录线程
    thread = threading.Thread(
        target=transcribe_task,
        args=(task_id, file_path, options, progress_queue, stop_event)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'success': True,
        'task_id': task_id
    })

def transcribe_task(task_id, file_path, options, progress_queue, stop_event):
    """执行转录任务的线程函数"""
    try:
        def progress_callback(progress, message):
            progress_queue.put({
                'progress': progress,
                'message': message
            })
            socketio.emit('progress_update', {
                'task_id': task_id,
                'progress': progress,
                'message': message
            })
        
        result = transcribe_audio(
            file_path=file_path,
            options=options,
            progress_callback=progress_callback,
            stop_event=stop_event
        )
        
        if stop_event.is_set():
            transcription_tasks[task_id]['status'] = 'cancelled'
            socketio.emit('transcription_cancelled', {'task_id': task_id})
        else:
            transcription_tasks[task_id]['result'] = result
            transcription_tasks[task_id]['status'] = 'completed'
            socketio.emit('transcription_completed', {
                'task_id': task_id,
                'text': result.get('text', ''),
                'has_segments': len(result.get('segments', [])) > 0
            })
        
        # 清理临时文件
        if result.get('temp_audio_path') and os.path.exists(result['temp_audio_path']):
            try:
                os.remove(result['temp_audio_path'])
            except:
                pass
    
    except Exception as e:
        import traceback
        error_msg = str(e)
        stack_trace = traceback.format_exc()
        debug_print(f"转录错误: {error_msg}\n{stack_trace}")
        
        transcription_tasks[task_id]['status'] = 'error'
        transcription_tasks[task_id]['error'] = error_msg
        
        socketio.emit('transcription_error', {
            'task_id': task_id,
            'error': error_msg
        })

@app.route('/cancel_transcription', methods=['POST'])
def cancel_transcription():
    """取消转录任务"""
    data = request.json
    task_id = data.get('task_id')
    
    if task_id in transcription_tasks:
        transcription_tasks[task_id]['stop_event'].set()
        return jsonify({'success': True})
    
    return jsonify({'error': '任务不存在'}), 404

@app.route('/get_result', methods=['GET'])
def get_result():
    """获取转录结果"""
    task_id = request.args.get('task_id')
    
    if task_id in transcription_tasks:
        task = transcription_tasks[task_id]
        
        if task['status'] == 'completed':
            return jsonify({
                'success': True,
                'status': 'completed',
                'text': task['result'].get('text', ''),
                'segments': task['result'].get('segments', [])
            })
        elif task['status'] == 'error':
            return jsonify({
                'success': False,
                'status': 'error',
                'error': task.get('error', '未知错误')
            })
        else:
            return jsonify({
                'success': True,
                'status': task['status']
            })
    
    return jsonify({'error': '任务不存在'}), 404

@app.route('/download_srt', methods=['POST'])
def download_srt():
    """下载SRT字幕文件"""
    data = request.json
    task_id = data.get('task_id')
    
    if task_id not in transcription_tasks:
        return jsonify({'error': '任务不存在'}), 404
    
    task = transcription_tasks[task_id]
    if task['status'] != 'completed':
        return jsonify({'error': '转录尚未完成'}), 400
    
    try:
        # 生成SRT内容
        whisper_output = task['result'].get('text', '')
        srt_content = whisper_to_srt(whisper_output)
        
        # 创建临时文件
        file_path = task['file_path']
        filename = os.path.splitext(os.path.basename(file_path))[0] + '.srt'
        srt_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        with open(srt_path, 'w', encoding='utf-8') as f:
            f.write(srt_content)
        
        return jsonify({
            'success': True,
            'filename': filename
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/download/<filename>')
def download_file(filename):
    """下载文件"""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

@app.route('/save_config', methods=['POST'])
def update_config():
    """保存配置"""
    data = request.json
    config = load_config()
    
    if 'beam_size' in data:
        config['beam_size'] = int(data['beam_size'])
    
    if 'whisper_path' in data:
        config['WHISPER_CPP_PATH'] = data['whisper_path']
    
    save_config(config)
    return jsonify({'success': True})

@socketio.on('connect')
def handle_connect():
    """处理客户端连接"""
    debug_print(f"客户端已连接: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    """处理客户端断开连接"""
    debug_print(f"客户端已断开连接: {request.sid}")

if __name__ == '__main__':
    debug_print("启动 WebWhisper...")
    # 加载配置
    config = load_config()
    debug_print(f"使用配置: {config}")
    
    # 启动服务器
    socketio.run(app, host='0.0.0.0', port=5000, debug=True) 