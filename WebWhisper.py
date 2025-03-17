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
        whisper_dir = os.path.join(program_dir, "Whisper_win-x64")
        whisper_exe = os.path.join(whisper_dir, "whisper-cli.exe")
    else:
        # Linux 路径
        whisper_dir = os.path.join(program_dir, "Whisper_linux-x64")
        whisper_exe = os.path.join(whisper_dir, "whisper-cli")
    
    # 检查可执行文件是否存在
    if os.path.exists(whisper_exe):
        return whisper_exe
    elif os.path.exists(whisper_dir):
        return whisper_dir
    else:
        return whisper_dir  # 返回目录路径，即使它不存在

# 配置文件
CONFIG_FILE = 'web_config.json'

# 创建 Flask 应用
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB 最大上传限制
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 会话有效期1小时
socketio = SocketIO(app, manage_session=False)

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
        model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "whisper", f"ggml-{model_name}.bin")
        language = options.get('language', 'auto')
        beam_size = min(int(options.get('beam_size', 5)), 8)
        task = options.get('task', 'transcribe')
        
        # 检查模型文件是否存在
        if not os.path.exists(model_path):
            os.makedirs(os.path.dirname(model_path), exist_ok=True)
            debug_print(f"模型文件 {model_path} 不存在，请确保已下载模型")
            if progress_callback:
                progress_callback(0, f"错误: 模型文件 {model_path} 不存在")
            return {
                'text': f"错误: 模型文件 {model_path} 不存在，请确保已下载模型",
                'segments': [],
                'stderr': f"模型文件 {model_path} 不存在",
                'cancelled': True
            }
        
        # 创建临时文件 - 使用绝对路径
        temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
        os.makedirs(temp_dir, exist_ok=True)
        temp_wav_path = os.path.join(temp_dir, f"whisper_temp_{int(time.time())}.wav")
        
        debug_print(f"创建临时WAV文件: {temp_wav_path}")
        
        # 转换音频文件为WAV格式
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(file_path)
            audio.export(temp_wav_path, format="wav")
            debug_print(f"音频文件已转换为WAV格式: {temp_wav_path}")
        except Exception as e:
            debug_print(f"音频转换失败: {str(e)}")
            if progress_callback:
                progress_callback(0, f"音频转换失败: {str(e)}")
            return {
                'text': f"音频转换失败: {str(e)}",
                'segments': [],
                'stderr': str(e),
                'cancelled': True
            }
        
        # 检查临时文件是否存在
        if not os.path.exists(temp_wav_path):
            debug_print(f"临时WAV文件创建失败: {temp_wav_path}")
            if progress_callback:
                progress_callback(0, "临时WAV文件创建失败")
            return {
                'text': "临时WAV文件创建失败",
                'segments': [],
                'stderr': "临时WAV文件创建失败",
                'cancelled': True
            }
        
        # 构建 whisper-cli 命令
        executable = options.get('whisper_executable')
        if not os.path.isabs(executable):
            executable = os.path.join(os.path.dirname(os.path.abspath(__file__)), executable)
        
        # 确保可执行文件存在
        if not os.path.exists(executable):
            debug_print(f"Whisper可执行文件不存在: {executable}")
            if progress_callback:
                progress_callback(0, f"错误: Whisper可执行文件不存在: {executable}")
            return {
                'text': f"错误: Whisper可执行文件不存在: {executable}",
                'segments': [],
                'stderr': f"Whisper可执行文件不存在: {executable}",
                'cancelled': True
            }
        
        cmd = [
            executable,
            "-m", model_path,
            "-f", temp_wav_path,
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
                    debug_print(f"STDERR: {line.strip()}")
            
            stderr_thread = threading.Thread(target=read_stderr, daemon=True)
            stderr_thread.start()
            
            # 时间戳行的简化模式
            timestamp_pattern = (
                r'\[(\d{2}:\d{2}:\d{2}\.\d{3}) --> '      # group(1) 开始时间
                r'(\d{2}:\d{2}:\d{2}\.\d{3})\]'            # group(2) 结束时间
                r' (.*)'                                   # group(3) 文本
            )
            
            # 持续读取 stdout 以获取进度行
            last_progress_time = time.time()
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
                    debug_print(f"STDOUT: {line.strip()}")
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
                            progress = min(int((current_time / 100.0) * 100), 95)  # 假设音频长度为100秒，最大进度为95%
                            
                            # 限制进度更新频率，避免过多的更新
                            current_time = time.time()
                            if current_time - last_progress_time >= 0.5:  # 每0.5秒最多更新一次
                                if progress_callback:
                                    progress_callback(progress, f"转录中: {progress}% 完成")
                                last_progress_time = current_time
                        except Exception as e:
                            debug_print(f"解析进度时出错: {e}")
                else:
                    time.sleep(0.1)
            
            # 处理剩余的 stdout
            for line in process.stdout:
                stdout_lines.append(line)
                debug_print(f"STDOUT: {line.strip()}")
            
            # 等待 stderr 完成
            stderr_thread.join(timeout=1.0)
            
            # 检查进程退出代码
            exit_code = process.returncode
            debug_print(f"Whisper.cpp 进程退出，退出代码: {exit_code}")
            
            if exit_code != 0:
                stderr_text = ''.join(stderr_data)
                debug_print(f"Whisper.cpp 进程失败: {stderr_text}")
                if progress_callback:
                    progress_callback(0, f"转录失败: 进程退出代码 {exit_code}")
                return {
                    'text': f"转录失败: 进程退出代码 {exit_code}\n{stderr_text}",
                    'segments': [],
                    'stderr': stderr_text,
                    'cancelled': True,
                    'temp_audio_path': temp_wav_path
                }
        
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
                'cancelled': True,
                'temp_audio_path': temp_wav_path
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
                'cancelled': True,
                'temp_audio_path': temp_wav_path
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
            'cancelled': False,
            'temp_audio_path': temp_wav_path
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
        file_path = os.path.join(os.path.abspath(app.config['UPLOAD_FOLDER']), filename)
        file.save(file_path)
        
        # 创建任务ID
        task_id = str(int(time.time()))
        session['current_task_id'] = task_id
        session['current_file_path'] = file_path
        
        debug_print(f"文件已上传: {file_path}, 任务ID: {task_id}, 会话ID: {session.sid if hasattr(session, 'sid') else '未知'}")
        
        # 确保会话数据被保存
        session.modified = True
        
        return jsonify({
            'success': True,
            'filename': filename,
            'task_id': task_id,
            'file_path': file_path
        })
    
    return jsonify({'error': '不支持的文件类型'}), 400

@app.route('/transcribe', methods=['POST'])
def start_transcription():
    """开始转录任务"""
    data = request.json
    task_id = data.get('task_id')
    file_path = data.get('file_path') or session.get('current_file_path')
    
    debug_print(f"转录请求: task_id={task_id}, file_path={file_path}, session={session}")
    
    if not task_id:
        return jsonify({'error': '无效的任务ID'}), 400
    
    if not file_path:
        # 尝试从任务ID推断文件路径
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            full_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if os.path.isfile(full_path) and os.path.getmtime(full_path) > time.time() - 300:  # 5分钟内上传的文件
                file_path = full_path
                session['current_file_path'] = file_path
                debug_print(f"从最近上传的文件推断文件路径: {file_path}")
                break
    
    if not file_path:
        return jsonify({'error': '无效的文件路径，请重新上传文件'}), 400
    
    # 检查文件是否存在
    if not os.path.exists(file_path):
        debug_print(f"文件不存在: {file_path}")
        return jsonify({'error': f'文件不存在: {file_path}'}), 400
    
    # 获取Whisper可执行文件路径
    whisper_path = data.get('whisper_path', get_default_whisper_cpp_path())
    
    # 确保使用绝对路径
    if not os.path.isabs(whisper_path):
        whisper_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), whisper_path)
    
    # 如果用户选择了目录，猜测实际的二进制文件名
    if os.path.isdir(whisper_path):
        if os.name == "nt":
            whisper_path = os.path.join(whisper_path, "whisper-cli.exe")
        else:
            whisper_path = os.path.join(whisper_path, "whisper-cli")
    
    # 检查可执行文件是否存在
    if not os.path.exists(whisper_path):
        debug_print(f"Whisper可执行文件不存在: {whisper_path}")
        return jsonify({'error': f'Whisper可执行文件不存在: {whisper_path}'}), 400
    
    # 转录选项
    options = {
        'model_name': data.get('model', 'base'),
        'task': data.get('task', 'transcribe'),
        'language': data.get('language', 'auto'),
        'beam_size': int(data.get('beam_size', 5)),
        'start_time': data.get('start_time', '00:00:00'),
        'end_time': data.get('end_time', ''),
        'generate_srt': data.get('generate_srt', False),
        'whisper_executable': whisper_path
    }
    
    debug_print(f"使用Whisper可执行文件: {options['whisper_executable']}")
    
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
            debug_print(f"进度更新: {progress}%, 消息: {message}")
            progress_queue.put({
                'progress': progress,
                'message': message
            })
            # 确保进度更新发送到前端
            try:
                socketio.emit('progress_update', {
                    'task_id': task_id,
                    'progress': progress,
                    'message': message
                }, namespace='/')
            except Exception as e:
                debug_print(f"发送进度更新失败: {str(e)}")
        
        debug_print(f"开始转录任务: {task_id}, 文件: {file_path}")
        result = transcribe_audio(
            file_path=file_path,
            options=options,
            progress_callback=progress_callback,
            stop_event=stop_event
        )
        
        debug_print(f"转录任务完成: {task_id}, 状态: {'已取消' if stop_event.is_set() else '成功'}")
        
        if stop_event.is_set():
            transcription_tasks[task_id]['status'] = 'cancelled'
            try:
                socketio.emit('transcription_cancelled', {'task_id': task_id}, namespace='/')
                debug_print(f"已发送取消通知: {task_id}")
            except Exception as e:
                debug_print(f"发送取消通知失败: {str(e)}")
        else:
            transcription_tasks[task_id]['result'] = result
            transcription_tasks[task_id]['status'] = 'completed'
            try:
                socketio.emit('transcription_completed', {
                    'task_id': task_id,
                    'text': result.get('text', ''),
                    'has_segments': len(result.get('segments', [])) > 0
                }, namespace='/')
                debug_print(f"已发送完成通知: {task_id}")
            except Exception as e:
                debug_print(f"发送完成通知失败: {str(e)}")
        
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
    
    # 确保必要的目录存在
    os.makedirs("temp", exist_ok=True)
    os.makedirs("models/whisper", exist_ok=True)
    
    # 检查模板目录是否存在
    if not os.path.exists("templates"):
        debug_print("创建模板目录...")
        os.makedirs("templates", exist_ok=True)
        
        # 创建基本的index.html模板
        with open("templates/index.html", "w", encoding="utf-8") as f:
            f.write("""
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>WebWhisper - 音频/视频转录</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/css/bootstrap.min.css">
    <style>
        body { padding-top: 20px; }
        .hidden { display: none; }
        .progress { height: 25px; }
        #result-container { white-space: pre-wrap; }
    </style>
</head>
<body>
    <div class="container">
        <h1 class="text-center mb-4">WebWhisper 音频/视频转录</h1>
        
        <div class="card mb-4">
            <div class="card-header">
                <h5>上传文件</h5>
            </div>
            <div class="card-body">
                <form id="upload-form">
                    <div class="mb-3">
                        <label for="file" class="form-label">选择音频或视频文件</label>
                        <input type="file" class="form-control" id="file" accept=".wav,.mp3,.m4a,.flac,.ogg,.wma,.mp4,.mov,.avi,.mkv">
                    </div>
                    <button type="submit" class="btn btn-primary">上传</button>
                </form>
            </div>
        </div>
        
        <div id="transcription-options" class="card mb-4 hidden">
            <div class="card-header">
                <h5>转录选项</h5>
            </div>
            <div class="card-body">
                <div class="mb-3">
                    <label for="model" class="form-label">选择模型</label>
                    <select class="form-select" id="model">
                        {% for model in models %}
                        <option value="{{ model.split('.')[1] }}">{{ model }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div class="mb-3">
                    <label for="language" class="form-label">语言</label>
                    <select class="form-select" id="language">
                        <option value="auto">自动检测</option>
                        <option value="zh">中文</option>
                        <option value="en">英文</option>
                        <option value="ja">日语</option>
                        <option value="ko">韩语</option>
                        <option value="fr">法语</option>
                        <option value="de">德语</option>
                        <option value="es">西班牙语</option>
                        <option value="ru">俄语</option>
                    </select>
                </div>
                <div class="mb-3">
                    <label for="task" class="form-label">任务</label>
                    <select class="form-select" id="task">
                        <option value="transcribe">转录</option>
                        <option value="translate">翻译为英文</option>
                    </select>
                </div>
                <div class="mb-3">
                    <label for="beam-size" class="form-label">Beam Size (1-8)</label>
                    <input type="number" class="form-control" id="beam-size" min="1" max="8" value="{{ config.beam_size }}">
                </div>
                <button id="start-transcription" class="btn btn-success">开始转录</button>
            </div>
        </div>
        
        <div id="progress-container" class="card mb-4 hidden">
            <div class="card-header">
                <h5>转录进度</h5>
            </div>
            <div class="card-body">
                <div class="progress mb-3">
                    <div id="progress-bar" class="progress-bar progress-bar-striped progress-bar-animated" role="progressbar" style="width: 0%"></div>
                </div>
                <p id="progress-message">准备中...</p>
                <button id="cancel-transcription" class="btn btn-danger">取消</button>
            </div>
        </div>
        
        <div id="result-card" class="card mb-4 hidden">
            <div class="card-header">
                <h5>转录结果</h5>
            </div>
            <div class="card-body">
                <div id="result-container" class="border p-3 mb-3 bg-light"></div>
                <button id="download-srt" class="btn btn-primary">下载SRT字幕</button>
                <button id="new-transcription" class="btn btn-secondary">新的转录</button>
            </div>
        </div>
    </div>
    
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/socket.io@4.6.1/client-dist/socket.io.min.js"></script>
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // 全局变量
            let currentTaskId = null;
            let currentFilePath = null;
            let socket = io();
            
            // 元素引用
            const uploadForm = document.getElementById('upload-form');
            const fileInput = document.getElementById('file');
            const transcriptionOptions = document.getElementById('transcription-options');
            const progressContainer = document.getElementById('progress-container');
            const progressBar = document.getElementById('progress-bar');
            const progressMessage = document.getElementById('progress-message');
            const resultCard = document.getElementById('result-card');
            const resultContainer = document.getElementById('result-container');
            const startTranscriptionBtn = document.getElementById('start-transcription');
            const cancelTranscriptionBtn = document.getElementById('cancel-transcription');
            const downloadSrtBtn = document.getElementById('download-srt');
            const newTranscriptionBtn = document.getElementById('new-transcription');
            
            // Socket.io 事件
            socket.on('connect', function() {
                console.log('已连接到服务器');
            });
            
            socket.on('disconnect', function() {
                console.log('与服务器断开连接');
            });
            
            socket.on('progress_update', function(data) {
                if (data.task_id === currentTaskId) {
                    progressBar.style.width = data.progress + '%';
                    progressMessage.textContent = data.message;
                }
            });
            
            socket.on('transcription_completed', function(data) {
                if (data.task_id === currentTaskId) {
                    progressContainer.classList.add('hidden');
                    resultCard.classList.remove('hidden');
                    resultContainer.textContent = data.text;
                }
            });
            
            socket.on('transcription_error', function(data) {
                if (data.task_id === currentTaskId) {
                    progressContainer.classList.add('hidden');
                    alert('转录错误: ' + data.error);
                }
            });
            
            socket.on('transcription_cancelled', function(data) {
                if (data.task_id === currentTaskId) {
                    progressContainer.classList.add('hidden');
                    alert('转录已取消');
                }
            });
            
            // 上传表单提交
            uploadForm.addEventListener('submit', function(e) {
                e.preventDefault();
                
                const file = fileInput.files[0];
                if (!file) {
                    alert('请选择文件');
                    return;
                }
                
                const formData = new FormData();
                formData.append('file', file);
                
                fetch('/upload', {
                    method: 'POST',
                    body: formData
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        currentTaskId = data.task_id;
                        currentFilePath = data.file_path;
                        transcriptionOptions.classList.remove('hidden');
                    } else {
                        alert('上传失败: ' + data.error);
                    }
                })
                .catch(error => {
                    console.error('上传错误:', error);
                    alert('上传错误: ' + error);
                });
            });
            
            // 开始转录
            startTranscriptionBtn.addEventListener('click', function() {
                if (!currentTaskId) {
                    alert('请先上传文件');
                    return;
                }
                
                const model = document.getElementById('model').value;
                const language = document.getElementById('language').value;
                const task = document.getElementById('task').value;
                const beamSize = document.getElementById('beam-size').value;
                
                transcriptionOptions.classList.add('hidden');
                progressContainer.classList.remove('hidden');
                progressBar.style.width = '0%';
                progressMessage.textContent = '准备中...';
                
                fetch('/transcribe', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        task_id: currentTaskId,
                        file_path: currentFilePath,
                        model: model,
                        language: language,
                        task: task,
                        beam_size: beamSize
                    })
                })
                .then(response => response.json())
                .then(data => {
                    if (!data.success) {
                        progressContainer.classList.add('hidden');
                        alert('转录请求失败: ' + data.error);
                    }
                })
                .catch(error => {
                    console.error('转录请求错误:', error);
                    progressContainer.classList.add('hidden');
                    alert('转录请求错误: ' + error);
                });
            });
            
            // 取消转录
            cancelTranscriptionBtn.addEventListener('click', function() {
                if (!currentTaskId) return;
                
                fetch('/cancel_transcription', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        task_id: currentTaskId
                    })
                })
                .then(response => response.json())
                .then(data => {
                    if (!data.success) {
                        alert('取消失败: ' + data.error);
                    }
                })
                .catch(error => {
                    console.error('取消错误:', error);
                    alert('取消错误: ' + error);
                });
            });
            
            // 下载SRT字幕
            downloadSrtBtn.addEventListener('click', function() {
                if (!currentTaskId) return;
                
                fetch('/download_srt', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        task_id: currentTaskId
                    })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        window.location.href = '/download/' + data.filename;
                    } else {
                        alert('下载失败: ' + data.error);
                    }
                })
                .catch(error => {
                    console.error('下载错误:', error);
                    alert('下载错误: ' + error);
                });
            });
            
            // 新的转录
            newTranscriptionBtn.addEventListener('click', function() {
                currentTaskId = null;
                currentFilePath = null;
                fileInput.value = '';
                resultCard.classList.add('hidden');
                uploadForm.classList.remove('hidden');
            });
        });
    </script>
</body>
</html>
            """)
        
        # 创建静态资源目录
        os.makedirs("static/css", exist_ok=True)
        os.makedirs("static/js", exist_ok=True)
    
    # 启动服务器
    socketio.run(app, host='0.0.0.0', port=5000, debug=True) 