"""
speaker.py — Streaming TTS engine using MLX chatterbox.

Public API:
    load_tts_model(model_id)  -> model
    BufferedSpeaker(model, voice, sr, max_buffers) -> speaker
        Persistent engine for background synthesis and playback.
"""

import threading
import queue
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from mlx_audio.tts.utils import load_model


def load_tts_model(model_id: str = "mlx-community/chatterbox-turbo-fp16"):
    """Load and return a chatterbox TTS model."""
    return load_model(model_id)


class BufferedSpeaker:
    """
    Manages background TTS synthesis and audio playback with buffering.
    Uses a text_queue to feed the engine and an audio_queue (max 4) for playback.
    """
    def __init__(self, model, voice: str = "af_heart", sr: int = 24000, max_buffers: int = 4):
        self.model = model
        self.voice = voice
        self.sr = sr
        self.max_buffers = max_buffers
        
        self.text_queue = queue.Queue()
        self.audio_queue = queue.Queue(maxsize=max_buffers)
        self.stop_event = threading.Event()
        
        self._state = self._State()
        
        # Start persistent worker threads
        self._synth_thread = threading.Thread(target=self._synthesis_loop, daemon=True)
        self._play_thread = threading.Thread(target=self._playback_loop, daemon=True)
        
        self._synth_thread.start()
        self._play_thread.start()

    class _State:
        def __init__(self):
            self.buf = np.zeros((0,), dtype=np.float32)
            self.fully_drained = False

    def feed(self, text: str, callback=None):
        """Add text to the synthesis queue with an optional callback when playback starts."""
        self.text_queue.put((text, callback))

    def stop(self):
        """Abort all current work and clear queues."""
        self.stop_event.set()
        # Clear queues
        while not self.text_queue.empty():
            try: self.text_queue.get_nowait()
            except queue.Empty: break
        while not self.audio_queue.empty():
            try: self.audio_queue.get_nowait()
            except queue.Empty: break
        
        # Give threads a moment to catch the stop signal
        time.sleep(0.1)
        self.stop_event.clear()
        self._state.buf = np.zeros((0,), dtype=np.float32)

    def _synthesis_loop(self):
        while True:
            item = self.text_queue.get()
            if item is None: break
            text, callback = item
            
            try:
                first_chunk = True
                for result in self.model.generate(text, voice=self.voice):
                    if self.stop_event.is_set():
                        break

                    chunk = np.array(result.audio).squeeze().astype(np.float32)
                    peak = np.max(np.abs(chunk)) + 1e-9
                    if peak > 1.0: chunk = chunk / peak

                    # Backpressure
                    while not self.stop_event.is_set():
                        try:
                            # Attach callback only to the first buffer of this text chunk
                            cb = callback if first_chunk else None
                            self.audio_queue.put((chunk, cb), timeout=0.1)
                            first_chunk = False
                            break
                        except queue.Full:
                            continue
            except Exception as e:
                print(f"Synthesis Error: {e}")

    def _playback_loop(self):
        finished_event = threading.Event()
        
        def callback(outdata, frames, time_info, status):
            out = np.zeros((frames,), dtype=np.float32)

            while self._state.buf.size < frames and not self.stop_event.is_set():
                try:
                    # Audio queue now yields (data, callback)
                    data, cb = self.audio_queue.get_nowait()
                    if cb:
                        # Non-blocking callback
                        threading.Thread(target=cb, daemon=True).start()
                    
                    self._state.buf = np.concatenate([self._state.buf, np.asarray(data, dtype=np.float32).reshape(-1)])
                except queue.Empty:
                    break

            n = min(frames, self._state.buf.size)
            if n > 0:
                out[:n] = self._state.buf[:n]
                self._state.buf = self._state.buf[n:]
            
            outdata[:, 0] = out

            if self.stop_event.is_set():
                raise sd.CallbackStop()

        while True:
            try:
                with sd.OutputStream(
                    samplerate=self.sr,
                    channels=1,
                    dtype="float32",
                    blocksize=2048,
                    callback=callback,
                    finished_callback=finished_event.set
                ):
                    while not self.stop_event.is_set():
                        finished_event.wait(0.1)
            except Exception:
                pass
            
            if self.stop_event.is_set():
                time.sleep(0.1)


def speak_text(model, text, voice="af_heart", sr=24000, stop_event=None):
    """Legacy one-shot wrapper. Blocks until done."""
    speaker = BufferedSpeaker(model, voice, sr)
    speaker.feed(text)
    
    # Poison pill to signal end
    speaker.text_queue.put(None)
    
    # Wait for synthesis and playback to drain (simple approach for legacy)
    while not speaker.text_queue.empty() or not speaker.audio_queue.empty():
        if stop_event and stop_event.is_set():
            speaker.stop()
            break
        time.sleep(0.1)
    
    # Wait a bit more for final buffer to clear
    time.sleep(0.5)
    speaker.stop()


if __name__ == "__main__":
    print("Loading model…")
    m = load_tts_model()
    print("Speaking…")
    speak_text(m, "This is a test of the buffered background speaker engine.")
    print("Done.")