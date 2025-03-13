"""
Media Player Module for SoftWhisper
├── MediaPlayer Class
│   ├── __init__(parent_frame, time_callback)
│   │   └── Initializes VLC instance and video rendering
│   ├── Video Control
│   │   ├── load_media(file_path) -> bool
│   │   ├── play()
│   │   ├── pause()
│   │   ├── stop()
│   │   └── set_position(percent)
│   ├── Position Tracking
│   │   ├── get_position_info() -> dict
│   │   ├── on_slider_press(event)
│   │   └── on_slider_release(event, position_value)
│   └── Utilities
│       └── get_duration() -> float
├── MediaPlayerUI Class
│   ├── __init__(parent_frame, play_button, pause_button, stop_button, slider, time_label)
│   │   └── Initializes UI controls for the media player
│   ├── UI Integration
│   │   ├── load_media(file_path) -> bool
│   │   ├── play()
│   │   ├── pause()
│   │   ├── stop()
│   │   ├── on_slider_press(event)
│   │   └── on_slider_release(event)
│   ├── Position Updates
│   │   ├── start_position_updates()
│   │   ├── update_position()
│   │   └── stop_position_updates()
│   └── Utilities
│       ├── format_time(seconds) -> str
│       └── cleanup()
"""

import os
import sys
import vlc
import tkinter as tk
from tkinter import ttk

class MediaPlayer:
    """
    Handles media playback core functionality.
    Provides a wrapper around VLC for media playback.
    """
    
    def __init__(self, parent_frame, time_callback=None):
        """
        Initialize the media player.
        
        Args:
            parent_frame: Tkinter frame that will contain the video display
            time_callback: Optional callback function for time updates
        """
        self.parent_frame = parent_frame
        self.time_callback = time_callback
        self.slider_dragging = False
        self.file_path = None
        
        # Initialize VLC
        self.vlc_instance = vlc.Instance()
        self.player = self.vlc_instance.media_player_new()
        
        # Configure the player based on platform
        self._setup_video_frame()
    
    def _setup_video_frame(self):
        """Setup the video display based on the current platform."""
        try:
            if sys.platform.startswith('linux'):
                self.player.set_xwindow(self.parent_frame.winfo_id())
            elif sys.platform == "win32":
                self.player.set_hwnd(self.parent_frame.winfo_id())
            elif sys.platform == "darwin":
                from ctypes import c_void_p
                self.player.set_nsobject(c_void_p(self.parent_frame.winfo_id()))
        except Exception as e:
            print(f"Error setting up video frame: {e}")
    
    def load_media(self, file_path):
        """
        Load a media file for playback.
        
        Args:
            file_path: Path to the audio/video file
            
        Returns:
            bool: True if media loaded successfully, False otherwise
        """
        try:
            self.file_path = file_path
            media = self.vlc_instance.media_new(file_path)
            self.player.set_media(media)
            return True
        except Exception as e:
            print(f"Error loading media: {e}")
            return False
    
    def play(self):
        """Start or resume media playback."""
        try:
            self.player.play()
            return True
        except Exception as e:
            print(f"Play error: {e}")
            return False
    
    def pause(self):
        """Pause media playback."""
        try:
            self.player.pause()
            return True
        except Exception as e:
            print(f"Pause error: {e}")
            return False
    
    def stop(self):
        """Stop media playback and reset position."""
        try:
            self.player.stop()
            return True
        except Exception as e:
            print(f"Stop error: {e}")
            return False
    
    def on_slider_press(self, event):
        """Handle slider press event."""
        self.slider_dragging = True
    
    def on_slider_release(self, event, position_value):
        """
        Handle slider release event by setting playback position.
        
        Args:
            event: The Tkinter event object
            position_value: The slider position value (0-100)
        """
        self.slider_dragging = False
        self.set_position(position_value)
    
    def set_position(self, value):
        """
        Set the playback position based on percentage.
        
        Args:
            value: Position value from 0-100
        """
        try:
            if self.player and self.player.get_length() > 0:
                position = value / 100
                self.player.set_position(position)
        except Exception as e:
            print(f"Error setting position: {e}")
    
    def get_position_info(self):
        """
        Get current playback position information.
        
        Returns:
            dict: Contains current_time, total_time in ms, and position %
        """
        length = self.player.get_length() if self.player else 0
        current_time = self.player.get_time() if self.player else 0
        position = self.player.get_position() * 100 if self.player else 0
        
        return {
            "current_time": current_time,
            "total_time": length,
            "position": position
        }
    
    def has_media(self):
        """Check if a media file is loaded."""
        return self.file_path is not None and self.player.get_media() is not None
    
    def get_filename(self):
        """Get the filename of the current media."""
        if not self.file_path:
            return None
        return os.path.basename(self.file_path)
    
    def get_duration(self):
        """Get the duration of the current media in seconds."""
        if not self.player:
            return 0
        return self.player.get_length() / 1000

class MediaPlayerUI:
    """
    Manages media player UI integration with Tkinter widgets.
    Wraps the core MediaPlayer functionality with UI-specific methods.
    """
    
    def __init__(self, parent_frame, play_button, pause_button, stop_button, 
                 slider, time_label, error_callback=None):
        """
        Initialize the media player UI manager.
        
        Args:
            parent_frame: Tkinter frame that will contain the video display
            play_button: Button widget for play control
            pause_button: Button widget for pause control
            stop_button: Button widget for stop control
            slider: Scale widget for position control
            time_label: Label widget for time display
            error_callback: Function to call with error messages
        """
        self.player = MediaPlayer(parent_frame)
        self.play_button = play_button
        self.pause_button = pause_button
        self.stop_button = stop_button
        self.slider = slider
        self.time_label = time_label
        self.error_callback = error_callback
        self.update_timer = None
        
        # Connect slider events
        self.slider.bind('<ButtonPress-1>', self.on_slider_press)
        self.slider.bind('<ButtonRelease-1>', self.on_slider_release)
    
    def load_media(self, file_path):
        """
        Load a media file and update UI elements.
        
        Args:
            file_path: Path to the audio/video file
            
        Returns:
            bool: Success of operation
        """
        try:
            if self.player.load_media(file_path):
                self.play_button.config(state=tk.NORMAL)
                self.pause_button.config(state=tk.NORMAL)
                self.stop_button.config(state=tk.NORMAL)
                self.slider.set(0)
                self.time_label.config(text="00:00:00 / 00:00:00")
                self.start_position_updates()
                return True
            else:
                self._show_error("Failed to load media file")
                return False
        except Exception as e:
            self._show_error(f"Failed to load media file for playback.\nError: {str(e)}")
            self.play_button.config(state=tk.DISABLED)
            self.pause_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.DISABLED)
            return False
    
    def play(self):
        """Play media and start position updates."""
        try:
            if self.player.play():
                self.start_position_updates()
            else:
                self._show_error("Failed to play media")
        except Exception as e:
            self._show_error(f"Failed to play media.\nError: {str(e)}")
    
    def pause(self):
        """Pause media playback."""
        try:
            if not self.player.pause():
                self._show_error("Failed to pause media")
        except Exception as e:
            self._show_error(f"Failed to pause media.\nError: {str(e)}")
    
    def stop(self):
        """Stop media playback and reset UI elements."""
        try:
            if self.player.stop():
                self.slider.set(0)
                self.time_label.config(text="00:00:00 / 00:00:00")
            else:
                self._show_error("Failed to stop media")
        except Exception as e:
            self._show_error(f"Failed to stop media.\nError: {str(e)}")
    
    def on_slider_press(self, event):
        """Handle slider press event."""
        self.player.on_slider_press(event)
    
    def on_slider_release(self, event):
        """Handle slider release and seek to position."""
        value = self.slider.get()
        self.player.on_slider_release(event, value)
    
    def start_position_updates(self):
        """Start periodic updates of the position slider and time label."""
        self.update_position()
    
    def update_position(self):
        """Update the slider position and time label based on current playback."""
        if not self.player:
            return
            
        try:
            position_info = self.player.get_position_info()
            
            if not self.player.slider_dragging and position_info["total_time"] > 0:
                # Update slider
                self.slider.set(position_info["position"])
                
                # Update time label
                current_time_str = self.format_time(position_info["current_time"] // 1000)
                total_time_str = self.format_time(position_info["total_time"] // 1000)
                self.time_label.config(text=f"{current_time_str} / {total_time_str}")
        except Exception as e:
            print(f"Error updating position: {e}")
            
        # Schedule next update
        self.update_timer = self.time_label.after(200, self.update_position)
    
    def stop_position_updates(self):
        """Stop periodic position updates."""
        if self.update_timer:
            self.time_label.after_cancel(self.update_timer)
            self.update_timer = None
    
    def cleanup(self):
        """Stop playback and clean up resources."""
        self.stop_position_updates()
        if self.player:
            self.player.stop()
    
    def format_time(self, seconds):
        """
        Format seconds as HH:MM:SS.
        
        Args:
            seconds: Time in seconds
            
        Returns:
            str: Formatted time string
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02}:{minutes:02}:{secs:02}"
    
    def _show_error(self, message):
        """Show error message via callback or messagebox."""
        if self.error_callback:
            self.error_callback(message)
        else:
            import tkinter.messagebox as messagebox
            messagebox.showerror("Media Player Error", message)