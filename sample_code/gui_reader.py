import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import threading
import queue
import os
import sys
import time
from pathlib import Path

# Fix imports to find sibling files
sys.path.insert(0, str(Path(__file__).parent))

from reader import BookReader
from speaker import load_tts_model, BufferedSpeaker
from splitter import BookSplitter

class BookReaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Python Book Reader")
        self.root.geometry("800x600")

        self.reader = None
        self.model = None
        self.speaker = None  # Persistent speaker engine
        self.voice = "af_heart"
        self.stop_event = threading.Event()
        self.playing = False
        self.model_loading = False
        self.splitter = BookSplitter(verbose=False)

        self._setup_ui()

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
        except Exception as e:
            self.handle_error("Save Note Error", e)

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
            self.update_display()
            self.log_status(f"Loaded: {os.path.basename(folder)}")
            self.btn_play.config(state=tk.NORMAL)
            self.btn_save_bkm.config(state=tk.NORMAL)
            self.btn_load_bkm.config(state=tk.NORMAL)
            self.btn_save_note.config(state=tk.NORMAL)
            if not self.model and not self.model_loading:
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
        except Exception as e:
            self.handle_error("Display Error", e)

    def load_model_async(self):
        self.model_loading = True
        self.log_status("Loading TTS model... (hang tight)")
        def _load():
            try:
                self.model = load_tts_model()
                self.speaker = BufferedSpeaker(self.model, voice=self.voice)
                self.log_status("TTS Model Ready!")
            except Exception as e:
                self.root.after(0, lambda: self.handle_error("Model Load Error", e))
            finally:
                self.model_loading = False
        threading.Thread(target=_load, daemon=True).start()

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

        self.playing = True
        self.stop_event.clear()
        self.btn_play.config(text="Pause")
        self.btn_stop.config(state=tk.NORMAL)
        self.log_status("Reading (Buffered)...")

        def _feeder():
            try:
                # Pump first few chunks to get the 4-buffer synthesis working immediately
                while self.playing and not self.stop_event.is_set():
                    scene = self.reader.current
                    text = self.reader.get_next_chunk(max_chars=500)
                    if text is None:
                        self.log_status("End of Book Reached")
                        break
                    
                    def _on_play(s=scene):
                        self.root.after(0, lambda: self._sync_ui_to_scene(s))
                    
                    self.speaker.feed(text, callback=_on_play)
                    
                    # Backpressure for text queue: don't get too far ahead of synthesis
                    # speaker.audio_queue (max 4) handles audio backpressure,
                    # but we also want to limit text queue to say 10 chunks.
                    while self.speaker.text_queue.qsize() > 5 and not self.stop_event.is_set():
                        time.sleep(0.5)
            except Exception as e:
                self.root.after(0, lambda: self.handle_error("Feeder Error", e))
        
        threading.Thread(target=_feeder, daemon=True).start()

    def _sync_ui_to_scene(self, scene):
        """Update UI to match what is currently playing."""
        if not self.playing: return
        self.update_display(scene)

    def _on_stop(self):
        self.btn_play.config(text="Start")
        self.btn_stop.config(state=tk.DISABLED)
        if not self.stop_event.is_set():
            self.log_status("Stopped.")

    def stop_playback(self):
        self.stop_event.set()
        if self.speaker:
            self.speaker.stop()
        self.playing = False
        self.log_status("Stopping...")
        self._on_stop()

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

if __name__ == "__main__":
    root = tk.Tk()
    app = BookReaderGUI(root)
    root.mainloop()
