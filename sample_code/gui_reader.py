import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import threading
import os
import sys
import time
import subprocess
import tempfile
import numpy as np
from pathlib import Path
import re

# Fix imports to find sibling files
sys.path.insert(0, str(Path(__file__).parent))

from reader import BookReader
from speaker import (
    DEFAULT_TTS_MODEL_ID,
    INTERNAL_TTS_SUPPORTED,
    BufferedSpeaker,
    available_tts_models,
    available_voices,
    default_voice_for_model,
    generation_kwargs,
    load_tts_model,
    model_label,
    play_audio_blocking,
    synthesize_audio,
)
from splitter import BookSplitter

LAST_READ_FILE = Path(__file__).parent / "last_read.json"
EXPORT_MODES = ("Chapter", "Scene")
M4A_EXPORT_RE = re.compile(r"^Chapter_(\d+)(?:_Scene_(\d+))?\.m4a$", re.IGNORECASE)


def export_units_for_scenes(scenes, mode: str):
    """Return export work units as (label, filename, scenes) tuples."""
    if mode not in EXPORT_MODES:
        raise ValueError(f"Unsupported export mode: {mode}")

    if mode == "Scene":
        return [
            (
                f"Chapter {sc.chapter}, Scene {sc.scene}",
                f"Chapter_{sc.chapter:03d}_Scene_{sc.scene:03d}.m4a",
                [sc],
            )
            for sc in scenes
        ]

    units = []
    chapters = {}
    for sc in scenes:
        chapters.setdefault(sc.chapter, []).append(sc)
    for ch_num, sc_list in chapters.items():
        units.append((f"Chapter {ch_num}", f"Chapter_{ch_num:03d}.m4a", sc_list))
    return units


def exported_m4a_sort_key(path: Path):
    """Sort current exporter filenames by chapter, then scene."""
    match = M4A_EXPORT_RE.match(path.name)
    if match:
        chapter = int(match.group(1))
        scene = int(match.group(2) or 0)
        return (0, chapter, scene, path.name.lower())
    return (1, path.name.lower())


def exported_m4a_marker_title(path: Path) -> str:
    """Return a readable marker title from an exported m4a filename."""
    match = M4A_EXPORT_RE.match(path.name)
    if not match:
        return path.stem.replace("_", " ")

    chapter = int(match.group(1))
    scene = match.group(2)
    if scene:
        return f"Chapter {chapter}, Scene {int(scene)}"
    return f"Chapter {chapter}"


def exported_m4a_files(input_dir: str | Path) -> list[Path]:
    """Return m4a files in the same numeric order as the TTS exporter."""
    folder = Path(input_dir)
    if not folder.is_dir():
        raise NotADirectoryError(f"Audio directory not found: {folder}")
    return sorted(folder.glob("*.m4a"), key=exported_m4a_sort_key)


def _ffmetadata_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("=", "\\=").replace(";", "\\;").replace("#", "\\#").replace("\n", " ")


def _ffconcat_quote(path: Path) -> str:
    return str(path.resolve()).replace("'", "'\\''")


def _probe_duration_seconds(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def _write_marked_m4a_metadata(files: list[Path], metadata_file: Path) -> None:
    current_ms = 0
    lines = [";FFMETADATA1"]
    for audio_file in files:
        duration_ms = max(1, round(_probe_duration_seconds(audio_file) * 1000))
        end_ms = current_ms + duration_ms
        lines.extend(
            [
                "",
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={current_ms}",
                f"END={end_ms}",
                f"title={_ffmetadata_escape(exported_m4a_marker_title(audio_file))}",
            ]
        )
        current_ms = end_ms
    metadata_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def create_marked_m4a(input_dir: str | Path, output_file: str | Path) -> Path:
    """
    Combine exported m4a files into one m4a with one chapter marker per source file.

    Files are ordered by the current exporter naming scheme:
    Chapter_001.m4a or Chapter_001_Scene_001.m4a.
    """
    output_path = Path(output_file)
    output_resolved = output_path.resolve()
    files = [path for path in exported_m4a_files(input_dir) if path.resolve() != output_resolved]
    if not files:
        raise ValueError(f"No .m4a files found in {input_dir}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        concat_file = tmp_dir / "concat.txt"
        metadata_file = tmp_dir / "chapters.ffmetadata"

        concat_file.write_text(
            "".join(f"file '{_ffconcat_quote(audio_file)}'\n" for audio_file in files),
            encoding="utf-8",
        )
        _write_marked_m4a_metadata(files, metadata_file)

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-i", str(metadata_file),
            "-map", "0:a",
            "-map_metadata", "1",
            "-map_chapters", "1",
            "-c", "copy",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"ffmpeg failed with exit code {result.returncode}")

    return output_path.resolve()

class BookReaderGUI:
    """
    BookReaderGUI: The primary Tkinter Application for the Text-to-Speech Book Reader.
    
    This interface integrates parsing (BookSplitter), navigation (BookReader), and 
    playback (BufferedSpeaker) into a cohesive Desktop experience.
    
    Key Responsibilities:
    1. UI Layout & State: Manages the Tkinter event loop, drawing controls, and tracking 
                          the current state (Playing vs Stopped).
    2. Session Management: Automatically saves and resumes the user's reading position 
                           (Chapter, Scene, Sentence) and settings (Voice Model).
    3. Multithreading: Coordinates the gapless TTS background threads to prevent 
                       the main UI event loop from freezing during intensive audio generation.
    4. Audio Export: Provides a background daemon (`_export_worker`) that synthesizes and 
                     encodes TTS text directly to .m4a files using FFmpeg via subprocess pipes.
    """
    def __init__(self, root):
        """
        Initialize the main GUI application.
        
        Args:
            root (tk.Tk): The base Tkinter window instance.
        """
        self.root = root
        self.root.title("Python Book Reader")
        self.root.geometry("800x800")

        self.reader = None
        self.model = None
        self.speaker = None  # Persistent speaker engine
        self.voice = default_voice_for_model(DEFAULT_TTS_MODEL_ID)

        self.stop_event = threading.Event()
        self.playing = False
        self.model_loading = False
        self.testing_voice = False
        self._played_index = 0
        self._played_sentence_index = 0
        self.splitter = BookSplitter(verbose=False)

        self._setup_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.exit_app)
        
        # Auto-load last session
        self.root.after(100, self.load_session)

    def _setup_ui(self):
        # Top controls
        ctrl_frame = tk.Frame(self.root)
        ctrl_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)

        self.btn_import = tk.Button(ctrl_frame, text="Import Text Book", command=self.import_book)
        self.btn_import.pack(side=tk.LEFT, padx=5)

        self.btn_load_book = tk.Button(ctrl_frame, text="Select Scene Folder", command=self.load_book)
        self.btn_load_book.pack(side=tk.LEFT, padx=5)

        self.btn_play = tk.Button(ctrl_frame, text="Start", command=self.toggle_play, state=tk.DISABLED)
        self.btn_play.pack(side=tk.LEFT, padx=5)

        self.btn_stop = tk.Button(ctrl_frame, text="Stop", command=self.stop_playback, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=5)

        self.btn_save_bkm = tk.Button(ctrl_frame, text="Save Bookmark", command=self.save_bookmark_dialog, state=tk.DISABLED)
        self.btn_save_bkm.pack(side=tk.LEFT, padx=5)

        self.btn_load_bkm = tk.Button(ctrl_frame, text="Load Bookmark", command=self.load_bookmark_dialog, state=tk.DISABLED)
        self.btn_load_bkm.pack(side=tk.LEFT, padx=5)

        self.btn_export = tk.Button(ctrl_frame, text="Export Audio", command=self.export_audio_dialog, state=tk.DISABLED)
        self.btn_export.pack(side=tk.LEFT, padx=5)

        self.btn_combine = tk.Button(ctrl_frame, text="Combine M4A", command=self.combine_audio_dialog)
        self.btn_combine.pack(side=tk.LEFT, padx=5)

        self.btn_exit = tk.Button(ctrl_frame, text="Exit", command=self.exit_app)
        self.btn_exit.pack(side=tk.RIGHT, padx=5)

        # TTS Configuration Frame
        tts_frame = tk.LabelFrame(self.root, text="TTS Settings")
        tts_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        tk.Label(tts_frame, text="Model:").pack(side=tk.LEFT, padx=5)
        self.tts_model_var = tk.StringVar(value=DEFAULT_TTS_MODEL_ID)
        models = available_tts_models()
        self.om_model = tk.OptionMenu(tts_frame, self.tts_model_var, *models, command=self.on_model_changed)
        self.om_model.pack(side=tk.LEFT)

        tk.Label(tts_frame, text="Voice:").pack(side=tk.LEFT, padx=(15, 5))
        self.tts_voice_var = tk.StringVar(value=self.voice)
        self.om_voice = tk.OptionMenu(tts_frame, self.tts_voice_var, *available_voices(self.tts_model_var.get()), command=self.on_voice_changed)
        self.om_voice.pack(side=tk.LEFT)

        tk.Label(tts_frame, text="Export:").pack(side=tk.LEFT, padx=(15, 5))
        self.export_mode_var = tk.StringVar(value="Chapter")
        self.om_export_mode = tk.OptionMenu(tts_frame, self.export_mode_var, *EXPORT_MODES)
        self.om_export_mode.pack(side=tk.LEFT)

        self.btn_test_voice = tk.Button(tts_frame, text="Test Voice", command=self.test_voice, state=tk.DISABLED)
        self.btn_test_voice.pack(side=tk.LEFT, padx=(15, 5))

        self.lbl_wpm = tk.Label(tts_frame, text="Generation WPM: --")
        self.lbl_wpm.pack(side=tk.LEFT, padx=5)

        # Navigation Controls
        nav_frame = tk.Frame(self.root)
        nav_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        self.btn_prev_ch = tk.Button(nav_frame, text="|<<", width=5, command=self.prev_chapter, state=tk.DISABLED)
        self.btn_prev_ch.pack(side=tk.LEFT, padx=2)

        self.btn_prev_sc = tk.Button(nav_frame, text="<<", width=5, command=self.prev_scene, state=tk.DISABLED)
        self.btn_prev_sc.pack(side=tk.LEFT, padx=2)

        self.btn_next_sc = tk.Button(nav_frame, text=">>", width=5, command=self.next_scene, state=tk.DISABLED)
        self.btn_next_sc.pack(side=tk.LEFT, padx=2)

        self.btn_next_ch = tk.Button(nav_frame, text=">>|", width=5, command=self.next_chapter, state=tk.DISABLED)
        self.btn_next_ch.pack(side=tk.LEFT, padx=2)

        # Labels
        self.lbl_status = tk.Label(self.root, text="Please select a book folder...")
        self.lbl_status.pack(side=tk.TOP, fill=tk.X, padx=10)

        self.lbl_chapter = tk.Label(self.root, text="", font=("Helvetica", 12, "bold"))
        self.lbl_chapter.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(10, 0))

        self.lbl_scene = tk.Label(self.root, text="", font=("Helvetica", 10, "italic"))
        self.lbl_scene.pack(side=tk.TOP, fill=tk.X, padx=10)

        # Scene Text Display
        self.txt_display = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, font=("Georgia", 12), height=15)
        self.txt_display.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.txt_display.config(state=tk.DISABLED)

        # Notes Section
        notes_frame = tk.LabelFrame(self.root, text="Scene Notes (appended to notes.txt in book folder)")
        notes_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        self.txt_notes = tk.Text(notes_frame, height=4, font=("Helvetica", 11))
        self.txt_notes.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)

        self.btn_save_note = tk.Button(notes_frame, text="Save Note", command=self.save_note, state=tk.DISABLED)
        self.btn_save_note.pack(side=tk.RIGHT, padx=5, pady=5)

        # Recent Notes Pane
        recent_frame = tk.LabelFrame(self.root, text="Recent Notes (last updates from notes.txt)")
        recent_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.txt_recent_notes = scrolledtext.ScrolledText(recent_frame, height=8, font=("Helvetica", 10), wrap=tk.WORD)
        self.txt_recent_notes.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.txt_recent_notes.config(state=tk.DISABLED)

    def on_model_changed(self, *args):
        if self.playing:
            self.stop_playback(silent=True)
        self._refresh_voice_options()
        if INTERNAL_TTS_SUPPORTED:
            self.load_model_async()

    def on_voice_changed(self, *args):
        self.voice = self.tts_voice_var.get()
        if self.speaker:
            self.speaker.set_voice(self.voice)
        self.save_session()

    def _refresh_voice_options(self, preferred_voice=None):
        model_id = self.tts_model_var.get()
        if model_id not in available_tts_models():
            model_id = DEFAULT_TTS_MODEL_ID
            self.tts_model_var.set(model_id)
        voices = available_voices(model_id)
        voice = preferred_voice or self.tts_voice_var.get()
        if voice not in voices:
            voice = default_voice_for_model(model_id)

        menu = self.om_voice["menu"]
        menu.delete(0, "end")
        for option in voices:
            menu.add_command(label=option, command=tk._setit(self.tts_voice_var, option, self.on_voice_changed))
        self.tts_voice_var.set(voice)
        self.voice = voice
        if self.speaker:
            self.speaker.set_voice(voice)

    def log_status(self, msg, is_error=False):
        color = "red" if is_error else "black"
        self.lbl_status.config(text=msg, fg=color)
        print(f"{'[ERROR] ' if is_error else ''}{msg}")

    def handle_error(self, title, error):
        """Centralized error handling to show message boxes and log to status."""
        msg = str(error)
        self.log_status(f"Error: {msg}", is_error=True)
        messagebox.showerror(title, msg)

    def save_note(self):
        """Append user note with current position and timestamp to notes.txt."""
        if not self.reader: return
        
        note_text = self.txt_notes.get("1.0", tk.END).strip()
        if not note_text:
            messagebox.showinfo("Note", "Note cannot be empty.")
            return

        try:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            pos = self.reader.position_info()
            notes_file = self.reader.scenes_dir / "notes.txt"
            
            with open(notes_file, "a", encoding="utf-8") as f:
                f.write(f"\n--- {timestamp} ---\n")
                f.write(f"Position: {pos}\n")
                f.write(f"Note: {note_text}\n")
                f.write("-" * 20 + "\n")
            
            self.txt_notes.delete("1.0", tk.END)
            self.log_status(f"Note saved to {os.path.basename(notes_file)}")
            self.update_notes_display()
        except Exception as e:
            self.handle_error("Save Note Error", e)

    def update_notes_display(self):
        """Reload the notes.txt file into the recent notes pane."""
        if not self.reader: return
        try:
            notes_file = self.reader.scenes_dir / "notes.txt"
            if not notes_file.exists():
                content = "(No notes yet)"
            else:
                # Read last 10KB to keep it snappy
                with open(notes_file, "r", encoding="utf-8") as f:
                    if os.path.getsize(notes_file) > 10000:
                        f.seek(os.path.getsize(notes_file) - 10000)
                        content = "... [earlier notes truncated] ...\n" + f.read()
                    else:
                        content = f.read()

            self.txt_recent_notes.config(state=tk.NORMAL)
            self.txt_recent_notes.delete("1.0", tk.END)
            self.txt_recent_notes.insert(tk.END, content.strip())
            self.txt_recent_notes.see(tk.END)
            self.txt_recent_notes.config(state=tk.DISABLED)
        except Exception as e:
            print(f"Error updating notes display: {e}")

    def import_book(self):
        file_path = filedialog.askopenfilename(
            title="Select Plain Text Book",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not file_path: return

        # Suggest output directory
        base_dir = Path(file_path).parent
        out_dir = filedialog.askdirectory(title="Select Output Folder for Scenes", initialdir=str(base_dir))
        if not out_dir: return

        self.log_status("Splitting book into scenes...")
        def _do_split():
            try:
                self.splitter.split_book(file_path, out_dir)
                self.root.after(0, lambda: self._after_import(out_dir))
            except Exception as e:
                self.root.after(0, lambda: self.handle_error("Split Error", e))
        threading.Thread(target=_do_split, daemon=True).start()

    def _after_import(self, folder):
        self.log_status(f"Import complete: {os.path.basename(folder)}")
        self._load_folder(folder)

    def load_book(self):
        folder = filedialog.askdirectory(title="Select Book Scenes Folder")
        if folder: self._load_folder(folder)

    def _load_folder(self, folder):
        try:
            self.reader = BookReader(folder)
            self._mark_played_position()
            self.update_display()
            self.log_status(f"Loaded: {os.path.basename(folder)}")
            self.btn_play.config(state=tk.NORMAL)
            self.btn_save_bkm.config(state=tk.NORMAL)
            self.btn_load_bkm.config(state=tk.NORMAL)
            self.btn_save_note.config(state=tk.NORMAL)
            self.btn_export.config(state=tk.NORMAL)
            self.btn_test_voice.config(state=tk.NORMAL)
            
            self.btn_prev_ch.config(state=tk.NORMAL)
            self.btn_prev_sc.config(state=tk.NORMAL)
            self.btn_next_sc.config(state=tk.NORMAL)
            self.btn_next_ch.config(state=tk.NORMAL)
            
            self.update_notes_display()
            
            if not self.speaker:
                self.init_speaker()
            
            if not self.model and not self.model_loading and INTERNAL_TTS_SUPPORTED:
                self.load_model_async()
        except Exception as e:
            self.handle_error("Load Error", e)

    def update_display(self, scene=None):
        """Update display with current scene text."""
        try:
            if not self.reader: return
            s = scene if scene else self.reader.current
            self.lbl_chapter.config(text=s.label)
            self.lbl_scene.config(text=s.title())

            self.txt_display.config(state=tk.NORMAL)
            self.txt_display.delete('1.0', tk.END)
            self.txt_display.insert(tk.END, s.text())
            self.txt_display.config(state=tk.DISABLED)
            if scene is None and not self.playing:
                self._mark_played_position()
        except Exception as e:
            self.handle_error("Display Error", e)

    def _mark_played_position(self, index=None, sentence_index=None):
        """Track the last position that was displayed or started playback."""
        if not self.reader:
            return
        self._played_index = self.reader._index if index is None else index
        self._played_sentence_index = self.reader._sentence_index if sentence_index is None else sentence_index

    def load_model_async(self):
        self.model_loading = True
        model_id = self.tts_model_var.get()
        if model_id not in available_tts_models():
            model_id = DEFAULT_TTS_MODEL_ID
            self.tts_model_var.set(model_id)
        voice = self.tts_voice_var.get()
        self.log_status(f"Loading TTS model {model_label(model_id)}... (hang tight)")
        def _load():
            try:
                self.model = load_tts_model(model_id)
                if not self.speaker:
                    self.speaker = BufferedSpeaker(self.model, voice=voice, model_id=model_id)
                else:
                    self.speaker.set_model(self.model, model_id, voice)
                self.log_status("TTS Model Ready!")
            except Exception as e:
                self.root.after(0, lambda: self.handle_error("Model Load Error", e))
            finally:
                self.model_loading = False
                if self.speaker:
                    self.speaker.set_model(self.model, model_id, voice)
        threading.Thread(target=_load, daemon=True).start()

    def init_speaker(self):
        """Initialize the speaker engine with current settings."""
        try:
            model_id = self.tts_model_var.get()
            self.speaker = BufferedSpeaker(model=self.model, voice=self.voice, model_id=model_id)
        except Exception as e:
            self.handle_error("Speaker Init Error", e)

    def toggle_play(self):
        if not self.model:
            messagebox.showinfo("Wait", "Model is still loading...")
            return
        if self.playing: self.stop_playback()
        else: self.start_playback()

    def start_playback(self):
        if not self.speaker:
            self.handle_error("Error", "Speaker engine not ready.")
            return
        if self.speaker.playback_error:
            self.handle_error("Playback Error", self.speaker.playback_error)
            return

        self.playing = True
        self.stop_event.clear()
        self.btn_play.config(text="Pause")
        self.btn_stop.config(state=tk.NORMAL)
        self.log_status("Reading (Buffered)...")

        def _feeder():
            try:
                # Pump first few chunks to get the 4-buffer synthesis working immediately
                while self.playing and not self.stop_event.is_set():
                    if self.speaker.playback_error:
                        raise RuntimeError(f"Playback failed: {self.speaker.playback_error}")
                    scene = self.reader.current
                    start_index = self.reader._index
                    start_sentence_index = self.reader._sentence_index
                    text = self.reader.get_next_chunk(max_chars=500)
                    if text is None:
                        self.log_status("End of Book Reached")
                        break
                    
                    def _on_play(s=scene, idx=start_index, sent_idx=start_sentence_index):
                        self.root.after(0, lambda: self._sync_ui_to_scene(s, idx, sent_idx))
                    
                    self.speaker.feed(text, callback=_on_play)
                    
                    # Backpressure for text queue: don't get too far ahead of synthesis
                    # speaker.audio_queue (max 4) handles audio backpressure,
                    # but we also want to limit text queue to say 10 chunks.
                    while self.speaker.text_queue.qsize() > 5 and not self.stop_event.is_set():
                        time.sleep(0.5)
            except Exception as e:
                self.root.after(0, lambda: self.handle_error("Feeder Error", e))
        
        threading.Thread(target=_feeder, daemon=True).start()

    def _sync_ui_to_scene(self, scene, index, sentence_index):
        """Update UI to match what is currently playing."""
        if not self.playing: return
        self._mark_played_position(index, sentence_index)
        self.update_display(scene)

    def _on_stop(self):
        self.btn_play.config(text="Start")
        self.btn_stop.config(state=tk.DISABLED)
        if not self.stop_event.is_set():
            self.log_status("Stopped.")

    def stop_playback(self, silent=False):
        self.stop_event.set()
        if self.speaker:
            self.speaker.stop()
        self.playing = False
        if not silent:
            self.log_status("Stopping...")
        self.save_session()
        self._on_stop()

    def save_session(self):
        """Save current reading position to last_read.json."""
        if not self.reader: return
        try:
            import json
            data = {
                "scenes_dir": str(self.reader.scenes_dir.resolve()),
                "index": self._played_index,
                "sentence_index": self._played_sentence_index,
                "tts_model": self.tts_model_var.get(),
                "tts_voice": self.tts_voice_var.get(),
            }
            LAST_READ_FILE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            print(f"Error saving session: {e}")

    def load_session(self):
        """Load the last read session if it exists."""
        if not LAST_READ_FILE.exists(): return
        try:
            import json
            data = json.loads(LAST_READ_FILE.read_text())
            
            if "tts_model" in data:
                saved_model = data["tts_model"]
                if saved_model not in available_tts_models():
                    saved_model = DEFAULT_TTS_MODEL_ID
                self.tts_model_var.set(saved_model)
                self._refresh_voice_options(data.get("tts_voice"))

            folder = data.get("scenes_dir")
            if folder and os.path.isdir(folder):
                self._load_folder(folder)
                if self.reader:
                    self.reader._index = data.get("index", 0)
                    self.reader._sentence_index = data.get("sentence_index", 0)
                    self._mark_played_position()
                    self.update_display()
        except Exception as e:
            print(f"Error loading session: {e}")

    def exit_app(self):
        """Save state and close the application."""
        self.stop_playback(silent=True)
        self.save_session()
        self.root.destroy()
        sys.exit(0)

    def _navigate(self, func):
        """Generic navigation wrapper to handle playback state."""
        if not self.reader: return
        
        was_playing = self.playing
        if was_playing:
            self.stop_playback(silent=True)
            
        if func():
            self.update_display()
            if was_playing:
                # Small delay to ensure speaker threads have cleared
                self.root.after(200, self.start_playback)
        else:
            self.log_status("End of navigation range.")

    def next_scene(self):
        self._navigate(self.reader.next_scene)

    def prev_scene(self):
        self._navigate(self.reader.prev_scene)

    def next_chapter(self):
        self._navigate(self.reader.next_chapter)

    def prev_chapter(self):
        self._navigate(self.reader.prev_chapter)

    def save_bookmark_dialog(self):
        if not self.reader: return
        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Bookmark", "*.json")],
            title="Save Bookmark"
        )
        if filename:
            self.reader.save_progress(Path(filename))
            self.log_status(f"Bookmark saved: {os.path.basename(filename)}")

    def load_bookmark_dialog(self):
        if not self.reader: return
        filename = filedialog.askopenfilename(
            filetypes=[("JSON Bookmark", "*.json")],
            title="Load Bookmark"
        )
        if filename:
            if self.reader._restore_progress(Path(filename)):
                self.update_display()
                self.log_status(f"Bookmark loaded: {os.path.basename(filename)}")
            else:
                messagebox.showerror("Error", "Could not load bookmark. Path might be different.")

    def combine_audio_dialog(self):
        input_dir = filedialog.askdirectory(title="Select Directory of Exported M4A Files")
        if not input_dir:
            return

        output_file = filedialog.asksaveasfilename(
            defaultextension=".m4a",
            filetypes=[("M4A Audio", "*.m4a")],
            initialdir=input_dir,
            initialfile="combined_with_markers.m4a",
            title="Save Combined M4A",
        )
        if not output_file:
            return

        self.btn_combine.config(state=tk.DISABLED)
        self.log_status(f"Combining audio from {os.path.basename(input_dir)}...")
        threading.Thread(target=self._combine_audio_worker, args=(Path(input_dir), Path(output_file)), daemon=True).start()

    def _combine_audio_worker(self, input_dir, output_file):
        try:
            combined = create_marked_m4a(input_dir, output_file)
            self.root.after(0, lambda: self.log_status(f"Combined audio saved: {combined.name}"))
        except Exception as e:
            self.root.after(0, lambda: self.handle_error("Combine Audio Error", e))
        finally:
            self.root.after(0, lambda: self.btn_combine.config(state=tk.NORMAL))

    def export_audio_dialog(self):
        if not self.reader: return
        if not self.model:
            messagebox.showerror("Export Error", "Export is currently only supported with local MLX models. Please load an internal model first.")
            return

        out_dir = filedialog.askdirectory(title="Select Output Directory for Audio Files", initialdir=str(self.reader.scenes_dir.parent))
        if not out_dir: return

        self.btn_export.config(state=tk.DISABLED)
        self.btn_play.config(state=tk.DISABLED)
        self.stop_playback(silent=True)
        self.btn_stop.config(state=tk.NORMAL)
        self.stop_event.clear()
        
        export_mode = self.export_mode_var.get()
        self.log_status(f"Starting {export_mode.lower()} export to {os.path.basename(out_dir)}...")
        threading.Thread(target=self._export_worker, args=(Path(out_dir), export_mode), daemon=True).start()

    def _export_worker(self, out_dir, export_mode="Chapter"):
        try:
            export_reader = BookReader(self.reader.scenes_dir)
            export_reader._index = self.reader._index
            export_reader._sentence_index = self.reader._sentence_index
            
            remaining_scenes = export_reader._scenes[export_reader._index:]
            if not remaining_scenes:
                self.root.after(0, lambda: self.log_status("No scenes to export."))
                return

            export_units = export_units_for_scenes(remaining_scenes, export_mode)

            sr = 24000
            if hasattr(self.speaker, 'sr'):
                sr = self.speaker.sr

            total_units = len(export_units)
            for idx, (unit_label, filename, sc_list) in enumerate(export_units, 1):
                if self.stop_event.is_set():
                    break

                outfile = out_dir / filename
                self.root.after(0, lambda label=unit_label, i=idx, t=total_units: self.log_status(f"Exporting {label} ({i}/{t})..."))

                cmd = [
                    "ffmpeg", "-y",
                    "-f", "f32le",
                    "-ar", str(sr),
                    "-ac", "1",
                    "-i", "pipe:0",
                    "-c:a", "aac",
                    "-b:a", "128k",
                    str(outfile)
                ]
                
                process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                try:
                    for sc in sc_list:
                        if self.stop_event.is_set():
                            break
                        sc_idx = export_reader._scenes.index(sc)
                        if export_reader._index != sc_idx:
                            export_reader._index = sc_idx
                            export_reader._sentence_index = 0
                            
                        while export_reader._index == sc_idx and export_reader._sentence_index < len(export_reader._scenes[sc_idx].sentences()):
                            if self.stop_event.is_set():
                                break
                            sent_idx = export_reader._sentence_index
                            total_sents = len(export_reader._scenes[sc_idx].sentences())
                            self.root.after(0, lambda label=unit_label, s=sent_idx, t=total_sents: self.log_status(f"Exporting {label}... ({s}/{t} sentences)"))
                            
                            text = export_reader.get_next_chunk(max_chars=500)
                            if not text:
                                break
                            
                            def _update_ui(t=text, s_scene=sc):
                                self.lbl_chapter.config(text=f"Exporting {s_scene.label}")
                                self.lbl_scene.config(text=s_scene.title())
                                self.txt_display.config(state=tk.NORMAL)
                                self.txt_display.delete('1.0', tk.END)
                                self.txt_display.insert(tk.END, t)
                                self.txt_display.config(state=tk.DISABLED)
                            self.root.after(0, _update_ui)

                            for result in self.model.generate(text, **generation_kwargs(self.tts_model_var.get(), self.tts_voice_var.get())):
                                if self.stop_event.is_set():
                                    break
                                chunk = np.array(result.audio).reshape(-1).astype(np.float32)
                                peak = np.max(np.abs(chunk)) + 1e-9
                                if peak > 1.0: chunk = chunk / peak
                                
                                if process.stdin:
                                    process.stdin.write(chunk.tobytes())
                finally:
                    if process.stdin:
                        process.stdin.close()
                    stderr = process.stderr.read() if process.stderr else b""
                    process.wait()
                    if process.returncode != 0:
                        err = stderr.decode("utf-8", errors="replace").strip()
                        raise RuntimeError(f"ffmpeg failed for {outfile.name}: {err or f'exit code {process.returncode}'}")

            if self.stop_event.is_set():
                self.root.after(0, lambda: self.log_status("Export Cancelled."))
            else:
                self.root.after(0, lambda: self.log_status("Export Complete!"))
            
        except Exception as e:
            self.root.after(0, lambda: self.handle_error("Export Error", e))
        finally:
            self.root.after(0, lambda: self.btn_export.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.btn_play.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.btn_stop.config(state=tk.DISABLED))

    def _first_book_words(self, limit=300):
        if not self.reader:
            return ""

        words = []
        for scene in self.reader._scenes:
            words.extend(re.findall(r"\S+", scene.text()))
            if len(words) >= limit:
                break
        return " ".join(words[:limit])

    def test_voice(self):
        if not self.reader:
            messagebox.showinfo("Test Voice", "Load a scene folder first.")
            return
        if self.playing:
            self.stop_playback(silent=True)
        if self.model_loading:
            messagebox.showinfo("Wait", "Model is still loading...")
            return
        if not self.model:
            self.load_model_async()
            messagebox.showinfo("Wait", "Model is loading. Try Test Voice again once it is ready.")
            return
        if self.testing_voice:
            return

        text = self._first_book_words(300)
        if not text:
            messagebox.showinfo("Test Voice", "No readable text found in the loaded book.")
            return

        model_id = self.tts_model_var.get()
        voice = self.tts_voice_var.get()
        word_count = len(re.findall(r"\S+", text))
        self.testing_voice = True
        self.btn_test_voice.config(state=tk.DISABLED)
        self.lbl_wpm.config(text="Generation WPM: ...")
        self.log_status(f"Testing {model_label(model_id)} / {voice} on {word_count} words...")

        def _run():
            try:
                audio, elapsed = synthesize_audio(self.model, text, model_id, voice)
                wpm = (word_count / elapsed) * 60 if elapsed else 0
                self.root.after(0, lambda: self.lbl_wpm.config(text=f"Generation WPM: {wpm:.0f}"))
                self.root.after(0, lambda: self.log_status(f"Generated {word_count} words in {elapsed:.1f}s ({wpm:.0f} WPM). Playing test..."))
                play_audio_blocking(audio, self.speaker.sr if self.speaker else 24000)
                self.root.after(0, lambda: self.log_status("Voice test complete."))
            except Exception as e:
                self.root.after(0, lambda: self.handle_error("Test Voice Error", e))
            finally:
                self.testing_voice = False
                self.root.after(0, lambda: self.btn_test_voice.config(state=tk.NORMAL if self.reader else tk.DISABLED))

        threading.Thread(target=_run, daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    app = BookReaderGUI(root)
    root.mainloop()
