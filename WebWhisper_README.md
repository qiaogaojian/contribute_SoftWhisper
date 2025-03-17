# WebWhisper

WebWhisper 是 SoftWhisper 的 Web 版本，一个基于 Whisper.cpp 的音频/视频转录工具。它提供了一个友好的 Web 界面，让您可以通过浏览器上传媒体文件并进行转录，无需安装桌面应用程序。

## 功能特点

- 支持多种音频和视频格式（WAV, MP3, M4A, FLAC, OGG, WMA, MP4, MOV, AVI, MKV）
- 内置媒体播放器，支持音频和视频播放
- 实时转录进度显示
- 支持多种 Whisper 模型选择
- 支持转录和翻译功能
- 可导出纯文本或 SRT 字幕文件
- 响应式设计，适配桌面和移动设备

## 安装要求

- Python 3.8 或更高版本
- Whisper.cpp（已编译的可执行文件）
- 足够的磁盘空间用于存储上传的媒体文件和模型

## 安装步骤

1. 克隆或下载本仓库

2. 创建并激活虚拟环境（可选但推荐）
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   venv\Scripts\activate     # Windows
   ```

3. 安装依赖
   ```bash
   pip install -r web_requirements.txt
   ```

4. 确保 Whisper.cpp 已编译并可用
   - 如果您已经有编译好的 Whisper.cpp，请确保路径正确
   - 如果没有，请按照 [Whisper.cpp 官方仓库](https://github.com/ggerganov/whisper.cpp) 的说明进行编译

5. 创建上传目录
   ```bash
   mkdir -p uploads
   ```

## 使用方法

1. 启动 WebWhisper 服务器
   ```bash
   python WebWhisper.py
   ```

2. 在浏览器中访问
   ```
   http://localhost:5000
   ```

3. 使用 Web 界面
   - 点击"选择音频/视频文件"上传媒体文件
   - 选择合适的模型和设置
   - 点击"开始转录"
   - 等待转录完成
   - 查看结果并根据需要导出文本或 SRT 字幕

## 配置选项

- **模型**：选择不同大小的 Whisper 模型（tiny、base、small、medium、large 等）
- **任务**：选择转录或翻译为英文
- **语言**：指定媒体文件的语言，或使用"auto"自动检测
- **Beam Size**：设置 beam search 大小（1-10），较大的值可能提高准确性但会降低速度
- **开始/结束时间**：可以只转录媒体文件的特定部分
- **生成 SRT 字幕**：启用此选项可生成带时间戳的 SRT 字幕文件
- **Whisper.cpp 可执行文件路径**：指定 Whisper.cpp 可执行文件的路径

## 故障排除

- **上传失败**：检查文件大小是否超过限制（默认 500MB）
- **转录错误**：检查 Whisper.cpp 路径是否正确，以及是否有足够的磁盘空间
- **模型下载失败**：检查网络连接和磁盘空间
- **服务器无法启动**：检查端口 5000 是否被占用，可以修改代码中的端口号

## 注意事项

- WebWhisper 默认监听所有网络接口（0.0.0.0），如果您在公共网络上运行，请考虑添加身份验证或防火墙保护
- 大文件的转录可能需要较长时间，请耐心等待
- 转录质量取决于所选模型的大小和媒体文件的质量

## 许可证

与 SoftWhisper 相同的许可证 