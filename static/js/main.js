/**
 * WebWhisper 前端 JavaScript
 */

// 全局变量
let socket;
let currentTaskId = null;
let mediaPlayer = null;
let isTranscribing = false;

// DOM 元素
const elements = {
    // 媒体播放器
    videoContainer: document.getElementById('video-container'),
    videoPlayer: document.getElementById('video-player'),
    audioPlayer: document.getElementById('audio-player'),
    noMediaText: document.getElementById('no-media-text'),
    playBtn: document.getElementById('play-btn'),
    pauseBtn: document.getElementById('pause-btn'),
    stopBtn: document.getElementById('stop-btn'),
    timeDisplay: document.getElementById('time-display'),
    
    // 文件上传
    fileUpload: document.getElementById('file-upload'),
    uploadInfo: document.getElementById('upload-info'),
    uploadFilename: document.getElementById('upload-filename'),
    
    // 转录控制
    startBtn: document.getElementById('start-btn'),
    stopTranscriptionBtn: document.getElementById('stop-btn'),
    
    // 状态和进度
    statusMessage: document.getElementById('status-message'),
    progressBar: document.getElementById('progress-bar'),
    consoleOutput: document.getElementById('console-output'),
    
    // 设置
    modelSelect: document.getElementById('model-select'),
    taskSelect: document.getElementById('task-select'),
    languageInput: document.getElementById('language-input'),
    beamSize: document.getElementById('beam-size'),
    startTime: document.getElementById('start-time'),
    endTime: document.getElementById('end-time'),
    generateSrt: document.getElementById('generate-srt'),
    whisperPath: document.getElementById('whisper-path'),
    saveConfigBtn: document.getElementById('save-config-btn'),
    
    // 转录结果
    transcriptionResult: document.getElementById('transcription-result'),
    
    // 导出
    exportTxtBtn: document.getElementById('export-txt-btn'),
    exportSrtBtn: document.getElementById('export-srt-btn')
};

// 初始化 Socket.IO
function initSocketIO() {
    socket = io();
    
    // 连接事件
    socket.on('connect', () => {
        console.log('已连接到服务器');
        appendConsole('已连接到服务器');
    });
    
    // 断开连接事件
    socket.on('disconnect', () => {
        console.log('与服务器断开连接');
        appendConsole('与服务器断开连接');
    });
    
    // 进度更新事件
    socket.on('progress_update', (data) => {
        if (data.task_id === currentTaskId) {
            updateProgress(data.progress, data.message);
        }
    });
    
    // 转录完成事件
    socket.on('transcription_completed', (data) => {
        if (data.task_id === currentTaskId) {
            transcriptionCompleted(data);
        }
    });
    
    // 转录取消事件
    socket.on('transcription_cancelled', (data) => {
        if (data.task_id === currentTaskId) {
            transcriptionCancelled();
        }
    });
    
    // 转录错误事件
    socket.on('transcription_error', (data) => {
        if (data.task_id === currentTaskId) {
            transcriptionError(data.error);
        }
    });
}

// 初始化媒体播放器
function initMediaPlayer() {
    // 播放按钮点击事件
    elements.playBtn.addEventListener('click', () => {
        const player = getActivePlayer();
        if (player) {
            player.play();
        }
    });
    
    // 暂停按钮点击事件
    elements.pauseBtn.addEventListener('click', () => {
        const player = getActivePlayer();
        if (player) {
            player.pause();
        }
    });
    
    // 停止按钮点击事件
    elements.stopBtn.addEventListener('click', () => {
        const player = getActivePlayer();
        if (player) {
            player.pause();
            player.currentTime = 0;
            updateTimeDisplay(0, player.duration || 0);
        }
    });
    
    // 时间更新事件
    function setupTimeUpdate(player) {
        player.addEventListener('timeupdate', () => {
            updateTimeDisplay(player.currentTime, player.duration);
        });
        
        player.addEventListener('loadedmetadata', () => {
            updateTimeDisplay(player.currentTime, player.duration);
        });
    }
    
    setupTimeUpdate(elements.videoPlayer);
    setupTimeUpdate(elements.audioPlayer);
}

// 获取当前活动的播放器
function getActivePlayer() {
    if (!elements.videoPlayer.classList.contains('d-none')) {
        return elements.videoPlayer;
    } else if (!elements.audioPlayer.classList.contains('d-none')) {
        return elements.audioPlayer;
    }
    return null;
}

// 更新时间显示
function updateTimeDisplay(currentTime, duration) {
    elements.timeDisplay.textContent = `${formatTime(currentTime)} / ${formatTime(duration)}`;
}

// 格式化时间
function formatTime(seconds) {
    if (isNaN(seconds) || seconds === Infinity) {
        return '00:00:00';
    }
    
    seconds = Math.floor(seconds);
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

// 初始化文件上传
function initFileUpload() {
    elements.fileUpload.addEventListener('change', (event) => {
        const file = event.target.files[0];
        if (!file) return;
        
        // 检查文件类型
        const fileType = file.type.split('/')[0];
        const fileExtension = file.name.split('.').pop().toLowerCase();
        
        // 创建 FormData
        const formData = new FormData();
        formData.append('file', file);
        
        // 显示上传信息
        elements.uploadInfo.classList.remove('d-none');
        elements.uploadFilename.textContent = `文件: ${file.name}`;
        updateStatus('正在上传文件...', 'info');
        
        // 发送上传请求
        fetch('/upload', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                currentTaskId = data.task_id;
                updateStatus(`文件 ${data.filename} 上传成功`, 'success');
                elements.startBtn.disabled = false;
                
                // 加载媒体文件
                loadMedia(file, fileType);
            } else {
                updateStatus(`上传失败: ${data.error}`, 'danger');
            }
        })
        .catch(error => {
            console.error('上传错误:', error);
            updateStatus(`上传错误: ${error.message}`, 'danger');
        });
    });
}

// 加载媒体文件
function loadMedia(file, fileType) {
    const url = URL.createObjectURL(file);
    
    // 重置播放器
    elements.videoPlayer.classList.add('d-none');
    elements.audioPlayer.classList.add('d-none');
    elements.noMediaText.classList.remove('d-none');
    
    if (fileType === 'video') {
        // 视频文件
        elements.videoPlayer.src = url;
        elements.videoPlayer.classList.remove('d-none');
        elements.noMediaText.classList.add('d-none');
        elements.videoPlayer.load();
    } else if (fileType === 'audio' || file.name.match(/\.(mp3|wav|ogg|flac|m4a)$/i)) {
        // 音频文件
        elements.audioPlayer.src = url;
        elements.audioPlayer.classList.remove('d-none');
        elements.noMediaText.classList.add('d-none');
        elements.audioPlayer.load();
    }
    
    // 启用播放控制按钮
    elements.playBtn.disabled = false;
    elements.pauseBtn.disabled = false;
    elements.stopBtn.disabled = false;
}

// 初始化转录控制
function initTranscriptionControls() {
    // 开始转录按钮点击事件
    elements.startBtn.addEventListener('click', () => {
        if (!currentTaskId) {
            updateStatus('请先上传文件', 'warning');
            return;
        }
        
        if (isTranscribing) {
            updateStatus('转录已在进行中', 'info');
            return;
        }
        
        startTranscription();
    });
    
    // 停止转录按钮点击事件
    elements.stopTranscriptionBtn.addEventListener('click', () => {
        if (!isTranscribing) {
            return;
        }
        
        cancelTranscription();
    });
    
    // 保存配置按钮点击事件
    elements.saveConfigBtn.addEventListener('click', () => {
        saveConfig();
    });
    
    // 导出文本按钮点击事件
    elements.exportTxtBtn.addEventListener('click', () => {
        const text = elements.transcriptionResult.value;
        if (!text) {
            updateStatus('没有可导出的文本', 'warning');
            return;
        }
        
        downloadText(text, 'transcription.txt');
    });
    
    // 导出SRT按钮点击事件
    elements.exportSrtBtn.addEventListener('click', () => {
        if (!currentTaskId) {
            updateStatus('没有可导出的字幕', 'warning');
            return;
        }
        
        downloadSrt();
    });
}

// 开始转录
function startTranscription() {
    // 获取设置
    const options = {
        task_id: currentTaskId,
        model: elements.modelSelect.value,
        task: elements.taskSelect.value,
        language: elements.languageInput.value,
        beam_size: elements.beamSize.value,
        start_time: elements.startTime.value,
        end_time: elements.endTime.value,
        generate_srt: elements.generateSrt.checked,
        whisper_path: elements.whisperPath.value
    };
    
    // 发送转录请求
    fetch('/transcribe', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(options)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            isTranscribing = true;
            updateStatus('转录已开始', 'info');
            elements.startBtn.disabled = true;
            elements.stopTranscriptionBtn.disabled = false;
            elements.progressBar.style.width = '0%';
            elements.transcriptionResult.value = '';
            elements.exportTxtBtn.disabled = true;
            elements.exportSrtBtn.disabled = true;
        } else {
            updateStatus(`转录请求失败: ${data.error}`, 'danger');
        }
    })
    .catch(error => {
        console.error('转录请求错误:', error);
        updateStatus(`转录请求错误: ${error.message}`, 'danger');
    });
}

// 取消转录
function cancelTranscription() {
    if (!currentTaskId) return;
    
    fetch('/cancel_transcription', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ task_id: currentTaskId })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            updateStatus('正在取消转录...', 'warning');
        } else {
            updateStatus(`取消转录失败: ${data.error}`, 'danger');
        }
    })
    .catch(error => {
        console.error('取消转录错误:', error);
        updateStatus(`取消转录错误: ${error.message}`, 'danger');
    });
}

// 转录完成
function transcriptionCompleted(data) {
    isTranscribing = false;
    updateStatus('转录完成', 'success');
    updateProgress(100, '转录完成');
    elements.startBtn.disabled = false;
    elements.stopTranscriptionBtn.disabled = true;
    
    // 显示转录结果
    elements.transcriptionResult.value = data.text;
    
    // 启用导出按钮
    elements.exportTxtBtn.disabled = false;
    elements.exportSrtBtn.disabled = false;
}

// 转录取消
function transcriptionCancelled() {
    isTranscribing = false;
    updateStatus('转录已取消', 'warning');
    elements.startBtn.disabled = false;
    elements.stopTranscriptionBtn.disabled = true;
}

// 转录错误
function transcriptionError(error) {
    isTranscribing = false;
    updateStatus(`转录错误: ${error}`, 'danger');
    elements.startBtn.disabled = false;
    elements.stopTranscriptionBtn.disabled = true;
}

// 更新进度
function updateProgress(progress, message) {
    elements.progressBar.style.width = `${progress}%`;
    elements.progressBar.setAttribute('aria-valuenow', progress);
    
    if (message) {
        updateStatus(message, 'info');
    }
}

// 更新状态
function updateStatus(message, type) {
    elements.statusMessage.textContent = message;
    
    // 根据类型设置颜色
    const colors = {
        'info': '#0dcaf0',
        'success': '#198754',
        'warning': '#ffc107',
        'danger': '#dc3545'
    };
    
    elements.statusMessage.style.color = colors[type] || '#000';
    
    // 添加到控制台
    appendConsole(message);
}

// 添加到控制台
function appendConsole(message) {
    const timestamp = new Date().toLocaleTimeString();
    elements.consoleOutput.value += `[${timestamp}] ${message}\n`;
    elements.consoleOutput.scrollTop = elements.consoleOutput.scrollHeight;
}

// 保存配置
function saveConfig() {
    const config = {
        beam_size: elements.beamSize.value,
        whisper_path: elements.whisperPath.value
    };
    
    fetch('/save_config', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(config)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            updateStatus('配置已保存', 'success');
        } else {
            updateStatus(`保存配置失败: ${data.error}`, 'danger');
        }
    })
    .catch(error => {
        console.error('保存配置错误:', error);
        updateStatus(`保存配置错误: ${error.message}`, 'danger');
    });
}

// 下载SRT
function downloadSrt() {
    fetch('/download_srt', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ task_id: currentTaskId })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // 创建下载链接
            const downloadUrl = `/download/${data.filename}`;
            window.location.href = downloadUrl;
            updateStatus('SRT文件下载已开始', 'success');
        } else {
            updateStatus(`SRT生成失败: ${data.error}`, 'danger');
        }
    })
    .catch(error => {
        console.error('SRT生成错误:', error);
        updateStatus(`SRT生成错误: ${error.message}`, 'danger');
    });
}

// 下载文本
function downloadText(text, filename) {
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    updateStatus('文本文件下载已开始', 'success');
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    initSocketIO();
    initMediaPlayer();
    initFileUpload();
    initTranscriptionControls();
    
    updateStatus('WebWhisper 已准备就绪', 'info');
}); 