"""
WebWhisper Whisper 工具模块
处理与 Whisper.cpp 的交互
"""

import os
import re
import time
import threading
import subprocess
import tempfile
from pathlib import Path
import psutil

from webwhisper.utils.logging_utils import logger
from webwhisper.config import config


def convert_audio_to_wav(file_path, temp_dir=None):
    """
    将音频文件转换为 WAV 格式
    
    Args:
        file_path: 音频文件路径
        temp_dir: 临时目录
    
    Returns:
        str: WAV 文件路径
    """
    try:
        from pydub import AudioSegment
        
        # 创建临时文件
        if temp_dir is None:
            temp_dir = config.get('temp_folder')
        
        os.makedirs(temp_dir, exist_ok=True)
        temp_wav_path = os.path.join(temp_dir, f"whisper_temp_{int(time.time())}.wav")
        
        # 转换音频
        audio = AudioSegment.from_file(file_path)
        audio.export(temp_wav_path, format="wav")
        
        logger.info(f"音频文件已转换为 WAV 格式: {temp_wav_path}")
        return temp_wav_path
    
    except Exception as e:
        logger.error(f"音频转换失败: {str(e)}")
        raise RuntimeError(f"音频转换失败: {str(e)}")


def build_whisper_command(model_path, audio_path, options):
    """
    构建 Whisper 命令
    
    Args:
        model_path: 模型路径
        audio_path: 音频文件路径
        options: 转录选项
    
    Returns:
        list: 命令列表
    """
    # 获取可执行文件路径
    executable = options.get('whisper_executable', config.get('whisper_executable'))
    
    # 确保使用绝对路径
    if not os.path.isabs(executable):
        # 使用项目根目录作为基准，而不是当前模块目录
        base_dir = Path(__file__).resolve().parent.parent.parent
        executable = os.path.join(base_dir, executable)
    
    # 如果用户选择了目录，猜测实际的二进制文件名
    if os.path.isdir(executable):
        if os.name == "nt":
            executable = os.path.join(executable, "whisper-cli.exe")
        else:
            executable = os.path.join(executable, "whisper-cli")
    
    # 检查可执行文件是否存在
    if not os.path.exists(executable):
        raise FileNotFoundError(f"Whisper 可执行文件不存在: {executable}")
    
    # 构建命令
    cmd = [
        executable,
        "-m", model_path,
        "-f", audio_path,
        "-bs", str(options.get('beam_size', 5)),
        "-pp",  # 实时进度
        "-l", options.get('language', 'auto')
    ]
    
    # 如果用户想要翻译为英文
    if options.get('task') == "translate":
        cmd.append("-translate")
    
    # 始终使用带时间戳的 JSON 输出
    cmd.append("-oj")
    
    return cmd


def run_whisper_process(cmd, progress_callback=None, stop_event=None):
    """
    运行 Whisper 进程
    
    Args:
        cmd: 命令列表
        progress_callback: 进度回调函数
        stop_event: 停止事件
    
    Returns:
        dict: 转录结果
    """
    logger.info(f"运行 Whisper.cpp 命令: {' '.join(cmd)}")
    
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
        logger.info(f"Whisper.cpp 进程已启动 (PID {process_id})。")
        
        # 在单独的线程上读取 stderr，这样它就不会阻塞
        def read_stderr():
            for line in iter(process.stderr.readline, ''):
                if stop_event and stop_event.is_set():
                    return
                stderr_data.append(line)
                logger.debug(f"STDERR: {line.strip()}")
        
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
                logger.info("停止事件已触发。终止 Whisper.cpp 进程...")
                
                # 在 Windows 或 *nix 上终止
                try:
                    parent = psutil.Process(process_id)
                    for child in parent.children(recursive=True):
                        child.kill()
                    parent.kill()
                except psutil.NoSuchProcess:
                    pass
                except Exception as e:
                    logger.error(f"终止进程时出错: {e}")
                
                cancelled = True
                break
            
            line = process.stdout.readline()
            if line:
                stdout_lines.append(line)
                logger.debug(f"STDOUT: {line.strip()}")
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
                        logger.error(f"解析进度时出错: {e}")
            else:
                time.sleep(0.1)
        
        # 处理剩余的 stdout
        for line in process.stdout:
            stdout_lines.append(line)
            logger.debug(f"STDOUT: {line.strip()}")
        
        # 等待 stderr 完成
        stderr_thread.join(timeout=1.0)
        
        # 检查进程退出代码
        exit_code = process.returncode
        logger.info(f"Whisper.cpp 进程退出，退出代码: {exit_code}")
        
        if exit_code != 0:
            stderr_text = ''.join(stderr_data)
            logger.error(f"Whisper.cpp 进程失败: {stderr_text}")
            if progress_callback:
                progress_callback(0, f"转录失败: 进程退出代码 {exit_code}")
            return {
                'text': f"转录失败: 进程退出代码 {exit_code}\n{stderr_text}",
                'segments': [],
                'stderr': stderr_text,
                'cancelled': True
            }
    
    except Exception as e:
        logger.error(f"转录过程中出错: {e}")
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
    timestamp_pattern = (
        r'\[(\d{2}:\d{2}:\d{2}\.\d{3}) --> '      # group(1) 开始时间
        r'(\d{2}:\d{2}:\d{2}\.\d{3})\]'            # group(2) 结束时间
        r' (.*)'                                   # group(3) 文本
    )
    
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


def transcribe_audio(file_path, options, progress_callback=None, stop_event=None):
    """
    使用 Whisper.cpp 转录音频
    
    Args:
        file_path: 音频文件路径
        options: 转录选项
        progress_callback: 进度回调函数
        stop_event: 停止事件
    
    Returns:
        dict: 转录结果
    """
    logger.info(f"开始转录文件: {file_path}")
    
    temp_wav_path = None
    try:
        # 转换音频为 WAV 格式
        temp_wav_path = convert_audio_to_wav(file_path, config.get('temp_folder'))
        
        # 获取模型路径
        model_name = options.get('model_name', 'base')
        model_path = os.path.join(
            config.get('models_folder'),
            f"ggml-{model_name}.bin"
        )
        
        # 检查模型文件是否存在
        if not os.path.exists(model_path):
            logger.error(f"模型文件不存在: {model_path}")
            if progress_callback:
                progress_callback(0, f"错误: 模型文件 {model_path} 不存在")
            return {
                'text': f"错误: 模型文件 {model_path} 不存在，请确保已下载模型",
                'segments': [],
                'stderr': f"模型文件 {model_path} 不存在",
                'cancelled': True
            }
        
        # 构建 Whisper 命令
        cmd = build_whisper_command(model_path, temp_wav_path, options)
        
        # 运行 Whisper 进程
        result = run_whisper_process(cmd, progress_callback, stop_event)
        
        # 添加临时文件路径到结果
        result['temp_audio_path'] = temp_wav_path
        
        return result
    
    except Exception as e:
        logger.error(f"转录失败: {str(e)}")
        return {
            'text': f"转录失败: {str(e)}",
            'segments': [],
            'stderr': str(e),
            'cancelled': True,
            'temp_audio_path': temp_wav_path
        }
    
    finally:
        # 清理临时文件
        if temp_wav_path and os.path.exists(temp_wav_path):
            try:
                os.remove(temp_wav_path)
                logger.debug(f"已删除临时文件: {temp_wav_path}")
            except:
                logger.warning(f"无法删除临时文件: {temp_wav_path}") 