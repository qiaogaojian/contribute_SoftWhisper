"""
WebWhisper 字幕工具模块
提供字幕格式转换功能
"""

import re
import os
from pathlib import Path
from webwhisper.utils.logging_utils import logger


def whisper_to_srt(whisper_output):
    """
    将 Whisper 输出转换为 SRT 格式
    
    Args:
        whisper_output: Whisper 输出文本
    
    Returns:
        str: SRT 格式文本
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


def segments_to_srt(segments):
    """
    将分段数据转换为 SRT 格式
    
    Args:
        segments: 分段数据列表
    
    Returns:
        str: SRT 格式文本
    """
    srt_parts = []
    
    for i, segment in enumerate(segments, 1):
        # 获取开始和结束时间
        start_seconds = segment.get('start', 0)
        end_seconds = segment.get('end', 0)
        text = segment.get('text', '').strip()
        
        # 转换为 SRT 时间格式 (HH:MM:SS,mmm)
        start_time = format_time(start_seconds)
        end_time = format_time(end_seconds)
        
        # 格式化为 SRT 条目
        srt_parts.append(f"{i}")
        srt_parts.append(f"{start_time} --> {end_time}")
        srt_parts.append(f"{text}")
        srt_parts.append("")  # 空行
    
    return "\n".join(srt_parts)


def format_time(seconds):
    """
    将秒数转换为 SRT 时间格式
    
    Args:
        seconds: 秒数
    
    Returns:
        str: SRT 时间格式 (HH:MM:SS,mmm)
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60
    milliseconds = int((seconds - int(seconds)) * 1000)
    
    return f"{hours:02d}:{minutes:02d}:{int(seconds):02d},{milliseconds:03d}"


def save_srt(srt_content, output_path):
    """
    保存 SRT 内容到文件
    
    Args:
        srt_content: SRT 内容
        output_path: 输出文件路径
    
    Returns:
        bool: 是否成功
    """
    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # 写入文件
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(srt_content)
        
        logger.info(f"SRT 文件已保存: {output_path}")
        return True
    except Exception as e:
        logger.error(f"保存 SRT 文件失败: {e}")
        return False


def save_whisper_as_srt(whisper_output, output_path):
    """
    将 Whisper 输出保存为 SRT 文件
    
    Args:
        whisper_output: Whisper 输出文本
        output_path: 输出文件路径
    
    Returns:
        bool: 是否成功
    """
    srt_content = whisper_to_srt(whisper_output)
    return save_srt(srt_content, output_path) 