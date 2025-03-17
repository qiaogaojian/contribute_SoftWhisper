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

// 调试日志函数
function debugLog(message, type = 'info') {
    const timestamp = new Date().toISOString();
    const logMessage = `[${timestamp}] [WebWhisper] [${type.toUpperCase()}] ${message}`;
    console.log(logMessage);
    
    // 如果有控制台输出元素，也更新它
    const consoleOutput = document.getElementById('console-output');
    if (consoleOutput) {
        consoleOutput.value += logMessage + '\n';
        consoleOutput.scrollTop = consoleOutput.scrollHeight;
    }
}

// 初始化 Socket.IO
function initSocketIO() {
    debugLog('初始化 Socket.IO 连接...');
    socket = io();
    
    // 连接事件
    socket.on('connect', () => {
        debugLog(`Socket.IO 已连接，Socket ID: ${socket.id}`);
    });
    
    // 断开连接事件
    socket.on('disconnect', (reason) => {
        debugLog(`Socket.IO 连接断开，原因: ${reason}`, 'warn');
    });
    
    // 重连事件
    socket.on('reconnect', (attemptNumber) => {
        debugLog(`Socket.IO 重连成功，尝试次数: ${attemptNumber}`);
    });
    
    socket.on('reconnect_attempt', (attemptNumber) => {
        debugLog(`Socket.IO 尝试重连，次数: ${attemptNumber}`, 'warn');
    });
    
    socket.on('reconnect_error', (error) => {
        debugLog(`Socket.IO 重连错误: ${error}`, 'error');
    });
    
    socket.on('reconnect_failed', () => {
        debugLog('Socket.IO 重连失败，已达到最大重试次数', 'error');
    });
    
    // 错误事件
    socket.on('error', (error) => {
        debugLog(`Socket.IO 错误: ${error}`, 'error');
    });
    
    // 进度更新事件
    socket.on('progress_update', (data) => {
        debugLog(`收到进度更新: task_id=${data.task_id}, progress=${data.progress}, message=${data.message}`);
        if (data.task_id === currentTaskId) {
            updateProgress(data.progress, data.message);
        } else {
            debugLog(`忽略非当前任务的进度更新: current=${currentTaskId}, received=${data.task_id}`, 'warn');
        }
    });
    
    // 转录完成事件
    socket.on('transcription_completed', (data) => {
        debugLog(`收到转录完成通知: task_id=${data.task_id}, has_segments=${data.has_segments}`);
        if (data.task_id === currentTaskId) {
            transcriptionCompleted(data);
        } else {
            debugLog(`忽略非当前任务的完成通知: current=${currentTaskId}, received=${data.task_id}`, 'warn');
        }
    });
    
    // 转录取消事件
    socket.on('transcription_cancelled', (data) => {
        debugLog(`收到转录取消通知: task_id=${data.task_id}`);
        if (data.task_id === currentTaskId) {
            transcriptionCancelled();
        } else {
            debugLog(`忽略非当前任务的取消通知: current=${currentTaskId}, received=${data.task_id}`, 'warn');
        }
    });
    
    // 转录错误事件
    socket.on('transcription_error', (data) => {
        debugLog(`收到转录错误通知: task_id=${data.task_id}, error=${data.error}`, 'error');
        if (data.task_id === currentTaskId) {
            transcriptionError(data.error);
        } else {
            debugLog(`忽略非当前任务的错误通知: current=${currentTaskId}, received=${data.task_id}`, 'warn');
        }
    });
    
    debugLog('Socket.IO 事件监听器已设置');
}

// 订阅任务进度
function subscribeToTask(taskId) {
    debugLog(`订阅任务进度: task_id=${taskId}`);
    if (!socket || !socket.connected) {
        debugLog('Socket.IO 未连接，无法订阅任务', 'error');
        return;
    }
    
    socket.emit('subscribe_task', { task_id: taskId }, (response) => {
        if (response && response.error) {
            debugLog(`订阅任务失败: ${response.error}`, 'error');
        } else {
            debugLog(`已成功订阅任务: ${taskId}`);
        }
    });
}

// 取消订阅任务进度
function unsubscribeFromTask(taskId) {
    debugLog(`取消订阅任务进度: task_id=${taskId}`);
    if (!socket || !socket.connected) {
        debugLog('Socket.IO 未连接，无法取消订阅', 'error');
        return;
    }
    
    socket.emit('unsubscribe_task', { task_id: taskId }, (response) => {
        if (response && response.error) {
            debugLog(`取消订阅任务失败: ${response.error}`, 'error');
        } else {
            debugLog(`已成功取消订阅任务: ${taskId}`);
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
    debugLog('处理转录完成');
    isTranscribing = false;
    updateStatus('转录完成', 'success');
    updateProgress(100, '转录完成');
    elements.startBtn.disabled = false;
    elements.stopTranscriptionBtn.disabled = true;
    
    // 显示转录结果
    elements.transcriptionResult.value = data.text;
    
    // 启用导出按钮
    elements.exportTxtBtn.disabled = false;
    elements.exportSrtBtn.disabled = !data.has_segments;
    
    debugLog(`转录结果已更新: ${data.text.length} 字符`);
    debugLog('界面已更新为完成状态');
}

// 转录取消
function transcriptionCancelled() {
    debugLog('处理转录取消');
    isTranscribing = false;
    updateStatus('转录已取消', 'warning');
    elements.startBtn.disabled = false;
    elements.stopTranscriptionBtn.disabled = true;
    
    updateProgress(0, '转录已取消');
    
    // 重置界面状态
    const startBtn = document.getElementById('start-btn');
    const stopBtn = document.getElementById('stop-btn');
    
    if (startBtn) startBtn.disabled = false;
    if (stopBtn) stopBtn.disabled = true;
    
    debugLog('界面已更新为取消状态');
}

// 转录错误
function transcriptionError(error) {
    debugLog(`处理转录错误: ${error}`, 'error');
    isTranscribing = false;
    updateStatus(`转录错误: ${error}`, 'danger');
    elements.startBtn.disabled = false;
    elements.stopTranscriptionBtn.disabled = true;
    
    updateProgress(0, `错误: ${error}`);
    
    // 重置界面状态
    const startBtn = document.getElementById('start-btn');
    const stopBtn = document.getElementById('stop-btn');
    
    if (startBtn) startBtn.disabled = false;
    if (stopBtn) stopBtn.disabled = true;
    
    debugLog('界面已更新为错误状态');
}

// 更新进度
function updateProgress(progress, message) {
    debugLog(`更新进度显示: ${progress}%, ${message}`);
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
    debugLog('页面加载完成，开始初始化...');
    initSocketIO();
    initMediaPlayer();
    initFileUpload();
    initTranscriptionControls();
    debugLog('初始化完成');
}); 