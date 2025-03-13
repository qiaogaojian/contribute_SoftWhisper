"""
SoftWhisper - Audio/Video Transcription Application using Whisper.cpp
"""

import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk
import threading
import os
import tempfile
import sys
import queue
import time
import json
import psutil
import urllib.request  # For downloading model files
import re

# Debug helper: Write messages to the original stdout
def debug_print(msg):
    sys.__stdout__.write(f"DEBUG: {msg}\n")
    sys.__stdout__.flush()

def get_default_whisper_cpp_path():
    program_dir = os.path.dirname(os.path.abspath(__file__))
    if os.name == "nt":
        # Default Windows path: a directory; we'll later append the executable name.
        return os.path.join(program_dir, "Whisper_win-x64")
    else:
        return os.path.join(program_dir, "Whisper_lin-x64")

# Allowed model filenames for automatic download.
ALLOWED_MODELS = [
    "ggml-tiny.bin", "ggml-tiny.en.bin",
    "ggml-base.bin", "ggml-base.en.bin",
    "ggml-small.bin", "ggml-small.en.bin",
    "ggml-medium.bin", "ggml-medium.en.bin",
    "ggml-large.bin", "ggml-large-v2.bin",
    "ggml-large-v3.bin", "ggml-large-v3-turbo.bin"
]

# Import media player module
from media_player import MediaPlayer, MediaPlayerUI

# Import our simplest SRT functions
from subtitles import save_whisper_as_srt, whisper_to_srt

import subprocess
import io
import signal
from pydub import AudioSegment

CONFIG_FILE = 'config.json'
MAX_CHUNK_DURATION = 120  # Maximum duration per chunk in seconds

# ------------------------------------------------------------------------------
# The transcribe_audio function with built-in logic to parse timestamps from
# Whisper.cpp JSON lines.
# ------------------------------------------------------------------------------
def transcribe_audio(file_path, options, progress_callback=None, status_callback=None, stop_event=None):
    """
    Handles calling whisper.cpp to do the actual transcription or translation,
    using JSON output and pydub for audio.
    """
    debug_print(f"transcribe_audio() => Processing file: {file_path}")
    model_name = options.get('model_name', 'base')
    model_path = os.path.join("models", "whisper", f"ggml-{model_name}.bin")
    language = options.get('language', 'auto')
    beam_size = min(int(options.get('beam_size', 5)), 8)
    task = options.get('task', 'transcribe')

    # Load audio with pydub
    audio = AudioSegment.from_file(file_path)
    audio_length = len(audio) / 1000.0

    # Handle start/end times without using validate_times
    start_time_str = options.get('start_time', '00:00:00').strip()
    end_time_str = options.get('end_time', '').strip()
    
    # Parse start time
    if start_time_str:
        try:
            # Simple parsing for HH:MM:SS
            parts = start_time_str.split(':')
            if len(parts) == 3:
                hours, minutes, seconds = map(int, parts)
                start_sec = hours * 3600 + minutes * 60 + seconds
            else:
                start_sec = 0
        except:
            start_sec = 0
    else:
        start_sec = 0
        
    # Parse end time
    if end_time_str:
        try:
            # Simple parsing for HH:MM:SS
            parts = end_time_str.split(':')
            if len(parts) == 3:
                hours, minutes, seconds = map(int, parts)
                end_sec = hours * 3600 + minutes * 60 + seconds
            else:
                end_sec = audio_length
        except:
            end_sec = audio_length
    else:
        end_sec = audio_length
    
    # Basic validation
    if start_sec < 0:
        start_sec = 0
    if start_sec >= audio_length:
        start_sec = 0
    if end_sec > audio_length:
        end_sec = audio_length
    if end_sec <= start_sec:
        end_sec = audio_length

    # Trim audio based on start/end times
    trimmed_audio = audio[start_sec * 1000 : end_sec * 1000]

    # Save to a temporary WAV file
    temp_audio_path = None
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        trimmed_audio.export(temp_file.name, format="wav")
        temp_audio_path = temp_file.name

    # Build whisper-cli command
    executable = options.get('whisper_executable')
    cmd = [
        executable,
        "-m", model_path,
        "-f", temp_audio_path,
        "-bs", str(beam_size),
        "-pp",  # real-time progress
        "-l", language
    ]
    # If user wants translation to English
    if task == "translate":
        cmd.append("-translate")

    # Always use JSON output with timestamps
    cmd.append("-oj")

    debug_print(f"Running Whisper.cpp with command: {' '.join(cmd)}")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    process = None
    stdout_lines = []
    stderr_data = []
    cancelled = False

    try:
        # encoding='utf-8' ensures we capture accented chars properly
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
        debug_print(f"Whisper.cpp process started (PID {process_id}).")

        # Read stderr on a separate thread so it doesn't block
        def read_stderr():
            for line in iter(process.stderr.readline, ''):
                if stop_event and stop_event.is_set():
                    return
                stderr_data.append(line)

        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stderr_thread.start()

        # Simplified pattern for timestamped lines
        timestamp_pattern = (
            r'\[(\d{2}:\d{2}:\d{2}\.\d{3}) --> '      # group(1) start time
            r'(\d{2}:\d{2}:\d{2}\.\d{3})\]'            # group(2) end time
            r' (.*)'                                   # group(3) text
        )

        # Continuously read stdout to get progress lines
        while process.poll() is None:
            if stop_event and stop_event.is_set():
                debug_print("Stop event triggered. Terminating Whisper.cpp process...")

                # Terminate on Windows or *nix
                try:
                    import psutil
                    parent = psutil.Process(process_id)
                    for child in parent.children(recursive=True):
                        child.kill()
                    parent.kill()
                except psutil.NoSuchProcess:
                    pass
                except Exception as e:
                    debug_print(f"Error terminating process: {e}")

                cancelled = True
                break

            line = process.stdout.readline()
            if line:
                stdout_lines.append(line)
                # Attempt to parse progress from the timestamps
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
                        progress = int((current_time / audio_length) * 100)
                        if progress_callback:
                            progress_callback(progress, f"Transcribing: {progress}% complete")
                    except Exception as e:
                        debug_print(f"Error parsing progress: {e}")
            else:
                time.sleep(0.1)

        # Process leftover stdout
        for line in process.stdout:
            stdout_lines.append(line)

        # Wait for stderr to finish
        stderr_thread.join(timeout=1.0)

    finally:
        # If still running, kill it
        if process and process.poll() is None:
            process.terminate()
            time.sleep(0.1)
            if process.poll() is None:
                process.kill()

    # If cancelled, clean up and exit
    if cancelled or (stop_event and stop_event.is_set()):
        if progress_callback:
            progress_callback(0, "Transcription cancelled")
        if temp_audio_path and os.path.exists(temp_audio_path):
            try:
                os.unlink(temp_audio_path)
            except Exception as e:
                debug_print(f"Error removing temp file: {str(e)}")

        return {
            'text': "Transcription cancelled by user.",
            'segments': [],
            'audio_length': audio_length,
            'stderr': ''.join(stderr_data),
            'cancelled': True
        }

    # Parse final text
    if progress_callback:
        progress_callback(90, "Processing transcription results...")

    output_text = "".join(stdout_lines).strip()
    segments = []
    full_text = ""

    # Parse segments from whisper output
    for line in output_text.split('\n'):
        line = line.strip()
        match = re.search(timestamp_pattern, line)
        if match:
            start_str = match.group(1)
            end_str   = match.group(2)
            text_str  = match.group(3).strip() if match.group(3) else ""

            # Convert start/end times from HH:MM:SS.mmm
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

    # If no timestamped segments, treat entire output as text
    if not segments:
        full_text = output_text
        segments.append({
            "start": 0.0,
            "end": audio_length,
            "text": full_text
        })

    if progress_callback:
        progress_callback(100, "Transcription completed successfully")

    # Return everything, but do NOT remove the temp file yet.
    return {
        'text': output_text,  # Return the raw Whisper output with timestamps
        'segments': segments,
        'temp_audio_path': temp_audio_path,
        'audio_length': audio_length,
        'stderr': ''.join(stderr_data),
        'cancelled': False
    }

class CustomProgressBar(tk.Canvas):
    def __init__(self, master, width, height, bg_color="#E0E0E0", fill_color="#4CAF50"):
        super().__init__(master, width=width, height=height, bg=bg_color, highlightthickness=0)
        self.fill_color = fill_color
        self.width = width
        self.height = height
        self.bar = self.create_rectangle(0, 0, 0, height, fill=fill_color, width=0)

    def set_progress(self, percentage):
        fill_width = int(self.width * percentage / 100)
        self.coords(self.bar, 0, 0, fill_width, self.height)
        self.update_idletasks()

class ConsoleRedirector:
    def __init__(self, console_queue):
        self.console_queue = console_queue

    def write(self, message):
        if message:
            self.console_queue.put({'type': 'append', 'content': message})

    def flush(self):
        pass

class SoftWhisper:
    def __init__(self, root):
        debug_print("Initializing SoftWhisper")
        self.root = root
        self.root.title("SoftWhisper")
        self.set_window_centered(1000, 800)
        self.root.deiconify()
        self.root.resizable(False, False)

        # Initialize variables
        self.setup_variables()
        self.setup_queues()
        self.create_widgets()
        self.load_config()
        self.setup_callbacks()
        debug_print("SoftWhisper initialization complete.")

    def setup_variables(self):
        debug_print("Setting up variables")
        self.model_loaded = False
        self.previous_model = "base"
        self.model_var = tk.StringVar(value="base")
        self.task_var = tk.StringVar(value="transcribe")
        self.language_var = tk.StringVar(value="auto")
        self.beam_size_var = tk.IntVar(value=5)
        self.start_time_var = tk.StringVar(value="00:00:00")
        self.end_time_var = tk.StringVar(value="")
        self.srt_var = tk.BooleanVar(value=False)
        self.file_path = None
        self.transcription_thread = None
        self.model_loading_thread = None
        self.transcription_stop_event = threading.Event()
        self.model_stop_event = threading.Event()
        self.slider_dragging = False

        # Store final segments & text
        self.current_segments = None
        self.current_text = None

        self.WHISPER_CPP_PATH = tk.StringVar(value=get_default_whisper_cpp_path())

        num_cores = psutil.cpu_count(logical=True)
        self.num_threads = max(1, int(num_cores * 0.8))
        debug_print(f"Using {self.num_threads} threads (logical cores * 0.8)")

    def setup_queues(self):
        debug_print("Setting up queues")
        self.console_queue = queue.Queue()
        self.progress_queue = queue.Queue()
        sys.stdout = ConsoleRedirector(self.console_queue)
        sys.stderr = ConsoleRedirector(self.console_queue)

    def create_widgets(self):
        debug_print("Creating widgets")
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill="both", expand=True)

        # Left side: Media controls
        media_frame = tk.Frame(main_frame)
        media_frame.pack(side="left", fill="y", padx=10, pady=10)

        # Right side: Settings & output
        right_frame = tk.Frame(main_frame)
        right_frame.pack(side="right", fill="both", expand=True, padx=10, pady=10)

        # Video frame
        self.video_frame = tk.Frame(media_frame, width=300, height=200, bg='black')
        self.video_frame.pack(pady=10)
        self.video_frame.pack_propagate(0)

        # Playback controls
        playback_frame = tk.Frame(media_frame)
        playback_frame.pack(pady=10)
        self.play_button = tk.Button(playback_frame, text="Play", font=("Arial", 12), state=tk.DISABLED)
        self.play_button.grid(row=0, column=0, padx=5)
        self.pause_button = tk.Button(playback_frame, text="Pause", font=("Arial", 12), state=tk.DISABLED)
        self.pause_button.grid(row=0, column=1, padx=5)
        self.stop_media_button = tk.Button(playback_frame, text="Stop", font=("Arial", 12), state=tk.DISABLED)
        self.stop_media_button.grid(row=0, column=2, padx=5)

        self.slider = ttk.Scale(playback_frame, from_=0, to=100, orient='horizontal', length=300)
        self.slider.grid(row=1, column=0, columnspan=3, pady=10)
        self.time_label = tk.Label(playback_frame, text="00:00:00 / 00:00:00", font=("Arial", 10))
        self.time_label.grid(row=2, column=0, columnspan=3)

        # Media player UI
        self.media_player_ui = MediaPlayerUI(
            parent_frame=self.video_frame,
            play_button=self.play_button,
            pause_button=self.pause_button,
            stop_button=self.stop_media_button,
            slider=self.slider,
            time_label=self.time_label,
            error_callback=lambda msg: messagebox.showerror("Media Error", msg)
        )

        self.play_button.config(command=lambda: (debug_print("Play media requested"), self.media_player_ui.play()))
        self.pause_button.config(command=lambda: (debug_print("Pause media requested"), self.media_player_ui.pause()))
        self.stop_media_button.config(command=lambda: (debug_print("Stop media requested"), self.media_player_ui.stop()))

        # File selection
        self.select_file_button = tk.Button(media_frame, text="Select Audio/Video File",
                                            command=self.select_file, font=("Arial", 12))
        self.select_file_button.pack(pady=10)

        # Transcription controls
        buttons_frame = tk.Frame(media_frame)
        buttons_frame.pack(pady=5)
        self.start_button = tk.Button(buttons_frame, text="Start Transcription",
                                      command=self.start_transcription, font=("Arial", 12), state=tk.DISABLED)
        self.start_button.grid(row=0, column=0, padx=10, pady=5)
        self.stop_button = tk.Button(buttons_frame, text="Stop Transcription",
                                     command=self.stop_processing, font=("Arial", 12), state=tk.DISABLED)
        self.stop_button.grid(row=0, column=1, padx=10, pady=5)

        # Status/Progress
        self.status_label = tk.Label(right_frame, text="Checking Whisper.cpp model...", fg="blue",
                                     font=("Arial", 12), wraplength=700, justify="left")
        self.status_label.pack(pady=10)
        self.progress_bar = CustomProgressBar(right_frame, width=700, height=20)
        self.progress_bar.pack(pady=10)

        # Console output
        console_frame = tk.LabelFrame(right_frame, text="Console Output", padx=10, pady=10, font=("Arial", 12))
        console_frame.pack(padx=10, pady=10, fill="x")
        self.console_output_box = scrolledtext.ScrolledText(console_frame, wrap=tk.WORD,
                                                            width=80, height=5, state=tk.DISABLED,
                                                            font=("Courier New", 10))
        self.console_output_box.pack(pady=5, fill="x", expand=False)

        # Settings
        settings_frame = tk.LabelFrame(right_frame, text="Optional Settings", padx=10, pady=10, font=("Arial", 12))
        settings_frame.pack(padx=10, pady=10, fill="x")

        tk.Label(settings_frame, text="Model:", font=("Arial", 10)).grid(row=0, column=0, sticky="w", pady=5)
        model_options = [
            "tiny","tiny.en","base","base.en","small","small.en",
            "medium","medium.en","large","large-v2","large-v3","large-v3-turbo"
        ]
        self.model_menu = ttk.Combobox(settings_frame, textvariable=self.model_var,
                                       values=model_options, state="readonly", width=20, font=("Arial", 10))
        self.model_menu.grid(row=0, column=1, sticky="w", padx=5, pady=5)
        self.model_menu.bind("<<ComboboxSelected>>", self.on_model_change)

        tk.Label(settings_frame, text="Task:", font=("Arial", 10)).grid(row=1, column=0, sticky="w", pady=5)
        task_options = ["transcribe", "translate"]
        self.task_menu = ttk.Combobox(settings_frame, textvariable=self.task_var,
                                      values=task_options, state="readonly", width=20, font=("Arial", 10))
        self.task_menu.grid(row=1, column=1, sticky="w", padx=5, pady=5)

        tk.Label(settings_frame, text="Language:", font=("Arial", 10)).grid(row=2, column=0, sticky="w", pady=5)
        self.language_entry = tk.Entry(settings_frame, textvariable=self.language_var, width=20, font=("Arial", 10))
        self.language_entry.grid(row=2, column=1, sticky="w", padx=5, pady=5)
        tk.Label(settings_frame, text="(Use 'auto' for auto-detection)", font=("Arial", 8)).grid(row=2, column=2, sticky="w", pady=5)

        tk.Label(settings_frame, text="Beam Size:", font=("Arial", 10)).grid(row=3, column=0, sticky="w", pady=5)
        self.beam_size_spinbox = tk.Spinbox(settings_frame, from_=1, to=10, textvariable=self.beam_size_var,
                                            width=5, font=("Arial", 10))
        self.beam_size_spinbox.grid(row=3, column=1, sticky="w", padx=5, pady=5)

        tk.Label(settings_frame, text="Start Time [hh:mm:ss]:", font=("Arial", 10)).grid(row=4, column=0, sticky="w", pady=5)
        self.start_time_entry = tk.Entry(settings_frame, textvariable=self.start_time_var, width=10, font=("Arial", 10))
        self.start_time_entry.grid(row=4, column=1, sticky="w", padx=5, pady=5)

        tk.Label(settings_frame, text="End Time [hh:mm:ss]:", font=("Arial", 10)).grid(row=5, column=0, sticky="w", pady=5)
        self.end_time_entry = tk.Entry(settings_frame, textvariable=self.end_time_var, width=10, font=("Arial", 10))
        self.end_time_entry.grid(row=5, column=1, sticky="w", padx=5, pady=5)
        tk.Label(settings_frame, text="(Leave empty for full duration)", font=("Arial", 8)).grid(row=5, column=2, sticky="w", pady=5)

        alignment_frame = tk.Frame(settings_frame)
        alignment_frame.grid(row=6, column=0, columnspan=3, sticky="w", pady=5)
        self.srt_checkbox = tk.Checkbutton(alignment_frame, text="Generate SRT Subtitles", variable=self.srt_var)
        self.srt_checkbox.pack(side="left")

        tk.Label(settings_frame, text="Whisper.cpp Executable:", font=("Arial", 10)).grid(row=7, column=0, sticky="w", pady=5)
        self.whisper_location_entry = tk.Entry(settings_frame, textvariable=self.WHISPER_CPP_PATH,
                                               width=40, font=("Arial", 10))
        self.whisper_location_entry.grid(row=7, column=1, sticky="w", padx=5, pady=5)
        self.whisper_browse_button = tk.Button(settings_frame, text="Browse",
                                               command=self.browse_whisper_executable, font=("Arial", 10))
        self.whisper_browse_button.grid(row=7, column=2, sticky="w", padx=5, pady=5)

        # Transcription frame
        transcription_frame = tk.LabelFrame(right_frame, text="Transcription", padx=10, pady=10, font=("Arial", 12))
        transcription_frame.pack(padx=10, pady=10, fill="both", expand=True)
        self.transcription_box = scrolledtext.ScrolledText(transcription_frame, wrap=tk.WORD,
                                                           width=80, height=10, state=tk.DISABLED,
                                                           font=("Arial", 10))
        self.transcription_box.pack(pady=5, fill="both", expand=True)

        # Spacer
        spacer_frame = tk.Frame(media_frame, height=460)
        spacer_frame.pack(pady=5)

        # Export button
        export_frame = tk.Frame(media_frame)
        export_frame.pack(side="bottom", pady=10, before=spacer_frame)
        self.export_button = tk.Button(export_frame, text="Export Transcription",
                                       command=self.export_transcription, font=("Arial", 12),
                                       state=tk.DISABLED)
        self.export_button.pack(fill="x", padx=10, pady=5)

        debug_print("Widgets created.")

    # -----------------------
    # ADDED: Plain-text export if user didn't generate SRT
    # -----------------------
    def export_transcription(self):
        """
        Export the transcription.
        If user had SRT enabled, we'll convert Whisper output directly to SRT.
        Otherwise, we export plain text.
        """
        if not self.current_text:
            # Nothing to export
            return

        if self.srt_var.get():
            debug_print("Exporting as SRT")
            from subtitles import save_whisper_as_srt
            save_whisper_as_srt(
                self.current_text,  # Pass the raw Whisper output
                self.file_path,
                self.root,
                self.update_status
            )
        else:
            debug_print("Exporting as plain text (.txt)")
            initial_filename = os.path.splitext(os.path.basename(self.file_path))[0] + '.txt'
            initial_dir = os.path.dirname(self.file_path)

            save_path = filedialog.asksaveasfilename(
                title="Save Transcription as Text File",
                defaultextension=".txt",
                initialfile=initial_filename,
                initialdir=initial_dir,
                filetypes=[('Text File', '*.txt'), ('All Files', '*.*')],
                parent=self.root
            )
            if save_path:
                try:
                    with open(save_path, 'w', encoding='utf-8') as out_f:
                        out_f.write(self.current_text)
                    self.update_status(f"Plain text file saved to {save_path}", "green")
                except Exception as e:
                    msg = f"Error saving text file: {str(e)}"
                    self.update_status(msg, "red")
                    messagebox.showerror("TXT Saving Error", msg)
            else:
                self.update_status("Text file saving cancelled", "blue")

    def browse_whisper_executable(self):
        current_path = self.WHISPER_CPP_PATH.get()
        init_dir = os.path.dirname(current_path) if current_path else os.getcwd()
        file_path = filedialog.askopenfilename(
            title="Select Whisper.cpp Executable",
            initialdir=init_dir,
            filetypes=[("Executable Files", "*.exe" if os.name == "nt" else "*.*")]
        )
        if file_path:
            self.WHISPER_CPP_PATH.set(file_path)
            debug_print(f"User selected Whisper.cpp executable: {file_path}")

    def load_config(self):
        debug_print("Loading configuration")
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    self.beam_size_var.set(config.get('beam_size', 5))
                    if 'WHISPER_CPP_PATH' in config:
                        self.WHISPER_CPP_PATH.set(config.get('WHISPER_CPP_PATH'))
                    else:
                        self.WHISPER_CPP_PATH.set(get_default_whisper_cpp_path())
                debug_print("Configuration loaded.")
            except Exception as e:
                debug_print(f"Error loading config: {e}")
        else:
            self.WHISPER_CPP_PATH.set(get_default_whisper_cpp_path())
            debug_print("No configuration file found; using default WHISPER_CPP_PATH.")

    def save_config(self, *args, **kwargs):
        debug_print("Saving configuration")
        config = {
            'beam_size': self.beam_size_var.get(),
            'WHISPER_CPP_PATH': self.WHISPER_CPP_PATH.get()
        }
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=4)
            debug_print("Configuration saved.")
        except Exception as e:
            debug_print(f"Error saving config: {e}")

    def setup_callbacks(self):
        debug_print("Setting up callbacks")
        self.model_var.trace("w", self.save_config)
        self.check_queues()

    def load_model(self):
        debug_print("Entering load_model()")
        selected_model = self.model_var.get()
        try:
            self.progress_queue.put((0, f"Checking model '{selected_model}'..."))
            model_filename = f"ggml-{selected_model}.bin"
            model_path = os.path.join("models", "whisper", model_filename)
            debug_print(f"Looking for model file: {model_path}")
            if not os.path.exists(model_path):
                if model_filename in ALLOWED_MODELS:
                    debug_print(f"Model file not found, attempting download for {model_filename}...")
                    whisper_folder = os.path.join("models", "whisper")
                    if not os.path.exists(whisper_folder):
                        os.makedirs(whisper_folder)
                    url = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{model_filename}"
                    debug_print(f"Downloading model from {url}")

                    def download_reporthook(block_num, block_size, total_size):
                        downloaded = block_num * block_size
                        percentage = int(downloaded / total_size * 100) if total_size > 0 else 0
                        progress_message = f"Downloading {model_filename}: {percentage}%"
                        self.progress_queue.put((percentage, progress_message))

                    urllib.request.urlretrieve(url, model_path, reporthook=download_reporthook)
                    debug_print("Download successful.")
                    self.progress_queue.put((100, f"Download of {model_filename} complete"))
                else:
                    raise Exception(f"Model file {model_path} not found and automatic download is not supported for this model.")
            self.model_loaded = True
            self.previous_model = selected_model
            self.progress_queue.put((100, f"Model '{selected_model}' is ready (Whisper.cpp)"))
            debug_print("Model loaded successfully.")
            self.root.after(0, self.enable_buttons)
        except Exception as e:
            self.progress_queue.put((0, f"Error: {str(e)}"))
            self.console_queue.put({'type': 'append', 'content': f"Error loading model: {str(e)}\n"})
            messagebox.showerror("Model Loading Error", f"Failed to load model '{selected_model}'.\nError: {str(e)}")
            self.model_var.set(self.previous_model if hasattr(self, 'previous_model') else "base")
            self.root.after(0, self.enable_buttons)
            debug_print("load_model() encountered an error.")

    def on_model_change(self, event):
        debug_print("Model change requested")
        selected_model = self.model_var.get()
        if self.model_loaded and selected_model != self.previous_model:
            response = messagebox.askyesno("Change Model", "Changing the model will require a check. Continue?")
            if response:
                self.transcription_stop_event.set()
                self.model_loaded = False
                self.clear_transcription_box()
                self.clear_console_output()
                self.progress_bar.set_progress(0)
                self.update_status("Checking selected Whisper.cpp model...", "blue")
                self.disable_buttons()
                self.transcription_stop_event.clear()
                self.model_loading_thread = threading.Thread(target=self.load_model, daemon=True)
                self.model_loading_thread.start()
            else:
                self.model_var.set(self.previous_model)
        elif not self.model_loaded:
            self.update_status("Checking selected Whisper.cpp model...", "blue")
            self.disable_buttons()
            self.model_loading_thread = threading.Thread(target=self.load_model, daemon=True)
            self.model_loading_thread.start()

    def select_file(self):
        debug_print("User requested file selection")
        file_path = filedialog.askopenfilename(
            title="Select Audio/Video File",
            filetypes=[("Audio/Video Files", "*.wav *.mp3 *.m4a *.flac *.ogg *.wma *.mp4 *.mov *.avi *.mkv"), ("All Files", "*.*")]
        )
        if file_path:
            self.file_path = file_path
            filename = os.path.basename(file_path)
            if len(filename) > 50:
                filename = filename[:47] + '...'
            self.update_status(f"Selected file: {filename}", "blue")
            debug_print(f"File selected: {file_path}")

            # Clear old transcription data
            self.clear_transcription_box()
            self.clear_console_output()
            self.current_segments = None
            self.current_text = None
            self.export_button.config(state=tk.DISABLED)

            if self.model_loaded:
                self.start_button.config(state=tk.NORMAL)

            self.root.update_idletasks()
            self.media_player_ui.load_media(file_path)

            self.play_button.config(state=tk.NORMAL)
            self.pause_button.config(state=tk.NORMAL)
            self.stop_media_button.config(state=tk.NORMAL)

            self.root.update_idletasks()
        else:
            self.file_path = None
            self.start_button.config(state=tk.DISABLED)
            debug_print("No file selected.")

    def start_transcription(self):
        debug_print("Start transcription requested")
        if not self.file_path:
            messagebox.showwarning("No File Selected", "Please select an audio/video file to transcribe.")
            return
        if not self.model_loaded:
            messagebox.showwarning("Model Not Ready", "Please wait until the Whisper.cpp model is ready.")
            return

        self.disable_buttons()
        self.stop_button.config(state=tk.NORMAL)
        self.progress_bar.set_progress(0)
        self.clear_transcription_box()
        self.clear_console_output()
        self.export_button.config(state=tk.DISABLED)
        self.update_status("Preparing for transcription...", "orange")
        self.current_segments = None
        self.current_text = None
        self.transcription_stop_event.clear()

        self.transcription_thread = threading.Thread(target=self.transcribe_file, args=(self.file_path,), daemon=True)
        self.transcription_thread.start()
        debug_print("Transcription thread started.")

    def stop_processing(self):
        debug_print("Stop transcription requested")
        self.transcription_stop_event.set()
        self.update_status("Stopping transcription...", "red")
        self.stop_button.config(state=tk.DISABLED)
        self.root.after(0, self.enable_buttons)

    def transcribe_file(self, file_path: str):
        debug_print(f"transcribe_file() => {file_path}")
        try:
            lang = self.language_var.get().strip().lower() or "auto"
            debug_print(f"Language setting: '{lang}'")

            options = {
                'model_name': self.model_var.get(),
                'task': self.task_var.get(),
                'language': lang,
                'beam_size': self.beam_size_var.get(),
                'start_time': self.start_time_var.get().strip(),
                'end_time': self.end_time_var.get().strip(),
                'generate_srt': self.srt_var.get(),  # Pass the SRT checkbox state
                'parent_window': self.root,
                'whisper_executable': self.WHISPER_CPP_PATH.get()
            }

            # If user selected a directory for the exe, guess the actual binary name
            exe_path = options['whisper_executable']
            if os.path.isdir(exe_path):
                if os.name == "nt":
                    exe_path = os.path.join(exe_path, "whisper-cli.exe")
                else:
                    exe_path = os.path.join(exe_path, "whisper-cli")
                options['whisper_executable'] = exe_path

            executable_abs = os.path.abspath(options['whisper_executable'])
            debug_print(f"Using Whisper executable: {executable_abs}")

            # Build a rough command for debugging
            whisper_cmd = (f"{executable_abs} -m models/ggml-{options['model_name']}.bin "
                        f"-f {file_path} -l {options['language']} -bs {options['beam_size']}")
            if options['task'] == 'translate':
                whisper_cmd += " -tr"
            # Always use JSON output with timestamps
            whisper_cmd += " -oj"
            debug_print(f"Command template: {whisper_cmd}")

            def progress_callback(progress, message):
                if self.transcription_stop_event.is_set():
                    return
                self.progress_queue.put((progress, message))

            def status_callback(message, color):
                self.update_status(message, color)

            debug_print("Calling transcribe_audio()...")
            if not self.transcription_stop_event.is_set():
                result = transcribe_audio(
                    file_path=file_path,
                    options=options,
                    progress_callback=progress_callback,
                    status_callback=status_callback,
                    stop_event=self.transcription_stop_event
                )
                debug_print("Transcription completed or cancelled")

                if (not self.transcription_stop_event.is_set()) and not result.get('cancelled', False):
                    # Store raw whisper output in self.current_text
                    self.current_text = result['text']
                    self.update_status("Processing transcription results...", "blue")
                    self.root.update_idletasks()

                    # Display based on the SRT checkbox state
                    if self.srt_var.get():
                        # Always convert the whisper output to proper SRT format
                        debug_print("Converting to proper SRT format for display")
                        from subtitles import whisper_to_srt
                        srt_content = whisper_to_srt(self.current_text)
                        self.display_transcription(srt_content)
                    else:
                        # Display raw whisper output with timestamps
                        self.display_transcription(self.current_text)
                    
                    # Store segments for possible future use
                    self.current_segments = result['segments']

                    # If there's any text, enable "Export"
                    if len(self.current_text.strip()) > 0:
                        self.export_button.config(state=tk.NORMAL)

                    self.update_status("Transcription completed.", "green")
                elif result.get('cancelled', False):
                    self.update_status("Transcription cancelled by user.", "red")
                else:
                    self.update_status("Transcription aborted.", "red")

                # Cleanup temp audio if it was created
                if result.get('temp_audio_path') and os.path.exists(result['temp_audio_path']):
                    try:
                        os.remove(result['temp_audio_path'])
                    except:
                        pass
            else:
                self.update_status("Transcription aborted.", "red")
        except Exception as e:
            import traceback
            error_msg = str(e)
            stack_trace = traceback.format_exc()
            self.console_queue.put({'type': 'append', 'content': f"Error during transcription: {error_msg}\n{stack_trace}\n"})
            self.progress_queue.put((0, f"Error during transcription: {error_msg}"))
            messagebox.showerror("Transcription Error", f"Failed to transcribe the audio/video file.\nError: {error_msg}")
            debug_print(f"Transcription error: {error_msg}")
        finally:
            self.root.after(0, self.enable_buttons)

    def disable_buttons(self):
        self.select_file_button.config(state=tk.DISABLED)
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.DISABLED)
        self.play_button.config(state=tk.DISABLED)
        self.pause_button.config(state=tk.DISABLED)
        self.stop_media_button.config(state=tk.DISABLED)

    def enable_buttons(self):
        self.select_file_button.config(state=tk.NORMAL)
        if self.file_path and self.model_loaded:
            self.start_button.config(state=tk.NORMAL)
            self.play_button.config(state=tk.NORMAL)
            self.pause_button.config(state=tk.NORMAL)
            self.stop_media_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)

    def update_status(self, message, color):
        def update():
            self.status_label.config(text=message, fg=color)
        self.root.after(0, update)

    def check_queues(self):
        try:
            while True:
                progress, status_message = self.progress_queue.get_nowait()
                self.progress_bar.set_progress(progress)
                if status_message:
                    self.update_status(status_message, "blue")
                self.root.update_idletasks()
        except queue.Empty:
            pass
        try:
            while True:
                message_data = self.console_queue.get_nowait()
                self.console_output_box.config(state=tk.NORMAL)
                if message_data['type'] == 'overwrite':
                    self.console_output_box.delete("end-2l", "end-1l")
                    self.console_output_box.insert(tk.END, message_data['content'])
                else:
                    self.console_output_box.insert(tk.END, message_data['content'])
                self.console_output_box.see(tk.END)
                self.console_output_box.config(state=tk.DISABLED)
                self.root.update_idletasks()
        except queue.Empty:
            pass
        self.root.after(50, self.check_queues)

    def clear_transcription_box(self):
        self.transcription_box.config(state=tk.NORMAL)
        self.transcription_box.delete(1.0, tk.END)
        self.transcription_box.config(state=tk.DISABLED)

    def clear_console_output(self):
        self.console_output_box.config(state=tk.NORMAL)
        self.console_output_box.delete(1.0, tk.END)
        self.console_output_box.config(state=tk.DISABLED)

    def display_transcription(self, text):
        def update_ui():
            self.transcription_box.config(state=tk.NORMAL)
            self.transcription_box.delete(1.0, tk.END)
            self.transcription_box.insert(tk.END, text)
            self.transcription_box.see(tk.END)
            self.transcription_box.config(state=tk.DISABLED)
            self.root.update_idletasks()
        self.root.after(1, update_ui)

    def set_window_centered(self, width, height):
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width // 2) - (width // 2)
        y = (screen_height // 2) - (height // 2)
        geometry_str = f"{width}x{height}+{x}+{y}"
        self.root.geometry(geometry_str)
        debug_print(f"Window geometry set to: {geometry_str}")

    def on_closing(self):
        debug_print("Closing application")
        self.transcription_stop_event.set()
        if self.transcription_thread and self.transcription_thread.is_alive():
            self.transcription_thread.join()
        if hasattr(self, 'media_player_ui'):
            self.media_player_ui.cleanup()
        self.root.destroy()

if __name__ == "__main__":
    debug_print("Starting SoftWhisper using Whisper.cpp...")
    root = tk.Tk()
    app = SoftWhisper(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.load_model()
    app.check_queues()
    debug_print("Entering mainloop")
    root.mainloop()