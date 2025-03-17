# WebWhisper

WebWhisper 是一个基于 Whisper.cpp 的音频/视频转录 Web 应用程序，它提供了一个友好的 Web 界面，让您可以通过浏览器上传媒体文件并进行转录，无需安装桌面应用程序。

## 功能特点

- 支持多种音频和视频格式（WAV, MP3, M4A, FLAC, OGG, WMA, MP4, MOV, AVI, MKV）
- 内置媒体播放器，支持音频和视频播放
- 实时转录进度显示
- 支持多种 Whisper 模型选择
- 支持转录和翻译功能
- 可导出纯文本或 SRT 字幕文件
- 响应式设计，适配桌面和移动设备

## 项目架构

WebWhisper 采用模块化设计，遵循以下原则：

- DRY（Don't Repeat Yourself）原则
- SOLID 原则（面向对象设计）
- KISS 原则（Keep It Simple, Stupid）
- YAGNI 原则（You Ain't Gonna Need It）
- 最少惊讶原则（Principle of Least Astonishment）
- 最少知识原则（Law of Demeter）
- 关注点分离原则（Separation of Concerns）
- 高内聚，低耦合（High Cohesion, Loose Coupling）

项目结构：

```
webwhisper/
├── app.py                  # 应用入口点
├── config.py               # 配置管理
├── requirements.txt        # 依赖管理
├── README.md               # 项目文档
├── static/                 # 静态资源
├── templates/              # 模板文件
├── uploads/                # 上传文件目录
├── temp/                   # 临时文件目录
├── models/                 # 模型目录
└── webwhisper/             # 核心模块
    ├── __init__.py
    ├── api/                # API 路由
    │   ├── __init__.py
    │   ├── routes.py
    │   └── websocket.py
    ├── core/               # 核心业务逻辑
    │   ├── __init__.py
    │   ├── transcriber.py
    │   ├── file_manager.py
    │   └── task_manager.py
    ├── models/             # 数据模型
    │   ├── __init__.py
    │   └── task.py
    └── utils/              # 工具函数
        ├── __init__.py
        ├── whisper_utils.py
        ├── subtitle_utils.py
        └── logging_utils.py
```

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
   pip install -r requirements.txt
   ```

4. 确保 Whisper.cpp 已编译并可用
   - 如果您已经有编译好的 Whisper.cpp，请确保路径正确
   - 如果没有，请按照 [Whisper.cpp 官方仓库](https://github.com/ggerganov/whisper.cpp) 的说明进行编译

5. 创建必要的目录
   ```bash
   mkdir -p uploads temp models/whisper logs
   ```

## 使用方法

1. 启动 WebWhisper 服务器
   ```bash
   python app.py
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

配置文件位于项目根目录下的 `web_config.json`，包含以下选项：

- **beam_size**: Beam search 大小（1-8），较大的值可能提高准确性但会降低速度
- **whisper_executable**: Whisper.cpp 可执行文件的路径
- **upload_folder**: 上传文件的存储目录
- **temp_folder**: 临时文件的存储目录
- **models_folder**: Whisper 模型的存储目录
- **max_upload_size**: 最大上传文件大小（字节）
- **allowed_extensions**: 允许上传的文件扩展名
- **allowed_models**: 允许使用的模型文件名
- **host**: 服务器监听的主机地址
- **port**: 服务器监听的端口
- **debug**: 是否启用调试模式

## 故障排除

- **上传失败**：检查文件大小是否超过限制（默认 500MB）
- **转录错误**：检查 Whisper.cpp 路径是否正确，以及是否有足够的磁盘空间
- **模型下载失败**：检查网络连接和磁盘空间
- **服务器无法启动**：检查端口是否被占用，可以修改配置文件中的端口号

## 注意事项

- WebWhisper 默认监听所有网络接口（0.0.0.0），如果您在公共网络上运行，请考虑添加身份验证或防火墙保护
- 大文件的转录可能需要较长时间，请耐心等待
- 转录质量取决于所选模型的大小和媒体文件的质量

## 许可证

与 SoftWhisper 相同的许可证
