"""Internal MLX TTS engine with asynchronous buffering and playback."""

import threading
import queue
import time
import os
from typing import Any, Callable

import numpy as np

TTS_CACHE_ROOT = "/Volumes/NVME/Source/tts"
HF_HOME = os.path.join(TTS_CACHE_ROOT, "huggingface")
HF_HUB_CACHE = os.path.join(HF_HOME, "hub")

os.environ.setdefault("HF_HOME", HF_HOME)
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", HF_HUB_CACHE)
os.environ.setdefault("HF_HUB_CACHE", HF_HUB_CACHE)
os.environ.setdefault("TRANSFORMERS_CACHE", os.path.join(HF_HOME, "transformers"))

# Detect internal TTS support
try:
    import sounddevice as sd
    from mlx_audio.tts.utils import load_model
    INTERNAL_TTS_SUPPORTED = True
except ImportError:
    INTERNAL_TTS_SUPPORTED = False

TTS_MODEL_CONFIGS: dict[str, dict[str, Any]] = {
    "mlx-community/Kokoro-82M-bf16": {
        "label": "Kokoro 82M",
        "voices": {
            "Heart": {"voice": "af_heart", "lang_code": "a", "speed": 1.0},
            "Bella": {"voice": "af_bella", "lang_code": "a", "speed": 1.0},
            "Nicole": {"voice": "af_nicole", "lang_code": "a", "speed": 1.0},
            "Sarah": {"voice": "af_sarah", "lang_code": "a", "speed": 1.0},
            "Sky": {"voice": "af_sky", "lang_code": "a", "speed": 1.0},
        },
        "default_voice": "Heart",
    },
    "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16": {
        "label": "Qwen3 0.6B Base",
        "voices": {
            "Chelsie": {"voice": "Chelsie", "lang_code": "English"},
            "Vivian": {"voice": "Vivian", "lang_code": "English"},
            "Ethan": {"voice": "Ethan", "lang_code": "English"},
        },
        "default_voice": "Chelsie",
    },
    "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16": {
        "label": "Qwen3 1.7B Base",
        "voices": {
            "Chelsie": {"voice": "Chelsie", "lang_code": "English"},
            "Vivian": {"voice": "Vivian", "lang_code": "English"},
            "Ethan": {"voice": "Ethan", "lang_code": "English"},
        },
        "default_voice": "Chelsie",
    },
    "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-bf16": {
        "label": "Qwen3 0.6B Custom Voice",
        "voices": {
            "Chelsie": {
                "voice": "Chelsie",
                "lang_code": "English",
                "instruct": "Calm, slow, slightly wistful computer voice.",
            },
            "Vivian": {
                "voice": "Vivian",
                "lang_code": "English",
                "instruct": "Calm, slow, slightly wistful computer voice.",
            },
            "Ethan": {
                "voice": "Ethan",
                "lang_code": "English",
                "instruct": "Calm, slow, slightly wistful computer voice.",
            },
        },
        "default_voice": "Chelsie",
    },
    "mlx-community/chatterbox-turbo-fp16": {
        "label": "Chatterbox Turbo",
        "voices": {"Default": {}},
        "default_voice": "Default",
    },
}

DEFAULT_TTS_MODEL_ID = "mlx-community/Kokoro-82M-bf16"


def available_tts_models() -> list[str]:
    """Return supported model IDs in display order."""
    return list(TTS_MODEL_CONFIGS)


def model_label(model_id: str) -> str:
    """Return a friendly model label for status text."""
    return TTS_MODEL_CONFIGS.get(model_id, {}).get("label", model_id)


def available_voices(model_id: str) -> list[str]:
    """Return voice names available for a supported model."""
    config = TTS_MODEL_CONFIGS.get(model_id)
    if not config:
        return ["Default"]
    return list(config["voices"])


def default_voice_for_model(model_id: str) -> str:
    """Return the preferred voice for a supported model."""
    config = TTS_MODEL_CONFIGS.get(model_id)
    if not config:
        return "Default"
    return config["default_voice"]


def generation_kwargs(model_id: str, voice_name: str | None = None) -> dict[str, Any]:
    """Return kwargs for mlx-audio generation for this model/voice pair."""
    config = TTS_MODEL_CONFIGS.get(model_id)
    if not config:
        return {"voice": "af_heart"}
    voice = voice_name or config["default_voice"]
    voices = config["voices"]
    if voice not in voices:
        voice = config["default_voice"]
    return dict(voices[voice])


def _audio_to_float32(audio: Any) -> np.ndarray:
    chunk = np.asarray(audio, dtype=np.float32).reshape(-1)
    if chunk.size == 0:
        return chunk
    peak = np.max(np.abs(chunk)) + 1e-9
    if peak > 1.0:
        chunk = chunk / peak
    return chunk


def synthesize_audio(model, text: str, model_id: str, voice_name: str | None = None) -> tuple[np.ndarray, float]:
    """Synchronously generate audio and return mono float32 audio plus elapsed seconds."""
    started = time.monotonic()
    chunks = []
    for result in model.generate(text=text, **generation_kwargs(model_id, voice_name)):
        chunks.append(_audio_to_float32(result.audio))
    elapsed = time.monotonic() - started
    if not chunks:
        raise RuntimeError("Model returned no audio chunks.")
    return np.concatenate(chunks), elapsed


def play_audio_blocking(audio: np.ndarray, sample_rate: int = 24000):
    """Play mono float32 audio and block until it completes."""
    if not INTERNAL_TTS_SUPPORTED:
        raise RuntimeError("Sounddevice is not available.")
    sd.play(np.asarray(audio, dtype=np.float32).reshape(-1), sample_rate)
    sd.wait()


def load_tts_model(model_id: str = DEFAULT_TTS_MODEL_ID):
    """
    Load an MLX-compatible TTS model from HuggingFace.
    
    This function acts as a wrapper around the `mlx_audio` `load_model` utility.
    It includes specific overrides required by certain model architectures.
    
    Args:
        model_id (str): The string identifier for the HuggingFace model repository.
                        Defaults to `mlx-community/Kokoro-82M-bf16`.
                        
    Returns:
        The instantiated MLX TTS model engine, or None if `mlx_audio` isn't available.
        
    Implementation Notes:
        - If "Qwen" is present in the `model_id` (e.g. Qwen3-TTS), it forcefully flags
          the underlying tokenizer to apply a regex fix (`fix_mistral_regex=True`) 
          to avert failure states in older underlying Mistral tokenizer dependencies.
    """
    if not INTERNAL_TTS_SUPPORTED:
        return None
        
    kwargs = {}
    if "Qwen" in model_id:
        kwargs["tokenizer_config"] = {"fix_mistral_regex": True}
        
    return load_model(model_id, **kwargs)

class BufferedSpeaker:
    """Manage background MLX TTS synthesis and audio playback with buffering."""
    def __init__(self, model=None, voice: str = "Heart", sr: int = 24000, max_buffers: int = 4, model_id: str = ""):
        self.model = model
        self.voice = voice
        self.sr = sr
        self.max_buffers = max_buffers
        self.model_id = model_id

        self.text_queue = queue.Queue()
        self.audio_queue = queue.Queue(maxsize=max_buffers)
        self.stop_event = threading.Event()
        self._state = self._State()
        self._lock = threading.Lock()
        self._active_synth = 0
        self._pending_text = 0
        self._playback_error: Exception | None = None

        self._synth_thread = threading.Thread(target=self._synthesis_loop, daemon=True)
        self._play_thread = threading.Thread(target=self._playback_loop, daemon=True)

        self._synth_thread.start()
        self._play_thread.start()

    class _State:
        def __init__(self):
            self.buf = np.zeros((0,), dtype=np.float32)
            self.fully_drained = False

    @property
    def playback_error(self) -> Exception | None:
        return self._playback_error

    def set_model(self, model, model_id: str = "", voice: str | None = None):
        """Swap the active MLX model without recreating worker threads."""
        self.model = model
        self.model_id = model_id
        if voice is not None:
            self.voice = voice

    def set_voice(self, voice: str):
        """Swap the active voice for subsequent synthesis work."""
        self.voice = voice

    def feed(self, text: str, callback: Callable | None = None):
        """Add text to the synthesis queue with an optional callback when playback starts."""
        with self._lock:
            self._pending_text += 1
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
        with self._lock:
            self._state.buf = np.zeros((0,), dtype=np.float32)
            self._active_synth = 0
            self._pending_text = 0

    def is_idle(self) -> bool:
        """Return True when synthesis queues and playback buffer are drained."""
        with self._lock:
            has_buffer = self._state.buf.size > 0
            active_synth = self._active_synth
            pending_text = self._pending_text
        return pending_text == 0 and self.audio_queue.empty() and active_synth == 0 and not has_buffer

    def wait_until_idle(self, timeout: float | None = None, poll_interval: float = 0.05) -> bool:
        """Block until all queued text has been synthesized and played, or timeout expires."""
        start = time.monotonic()
        while True:
            if self.playback_error:
                raise RuntimeError(f"Playback failed: {self.playback_error}") from self.playback_error
            if self.is_idle():
                return True
            if timeout is not None and time.monotonic() - start >= timeout:
                return False
            time.sleep(poll_interval)

    def _synthesis_loop(self):
        while True:
            item = self.text_queue.get()
            if item is None: break
            text, callback = item
            
            try:
                if not self.model:
                    print("TTS model is not loaded.")
                    continue
                with self._lock:
                    self._active_synth += 1
                try:
                    self._internal_synth(text, callback)
                finally:
                    with self._lock:
                        self._active_synth = max(0, self._active_synth - 1)
            except Exception as e:
                print(f"Synthesis Error: {e}")
            finally:
                with self._lock:
                    self._pending_text = max(0, self._pending_text - 1)

    def _internal_synth(self, text, callback):
        first_chunk = True
        for result in self.model.generate(text, **generation_kwargs(self.model_id, self.voice)):
            if self.stop_event.is_set():
                break

            chunk = _audio_to_float32(result.audio)

            while not self.stop_event.is_set():
                try:
                    cb = callback if first_chunk else None
                    self.audio_queue.put((chunk, cb), timeout=0.1)
                    first_chunk = False
                    break
                except queue.Full:
                    continue

    def _playback_loop(self):
        if not INTERNAL_TTS_SUPPORTED:
            print("Sounddevice not available. Playback loop disabled.")
            return

        finished_event = threading.Event()
        
        def callback(outdata, frames, time_info, status):
            if status:
                print(f"Playback status: {status}")

            out = np.zeros((frames,), dtype=np.float32)

            while not self.stop_event.is_set():
                with self._lock:
                    needs_audio = self._state.buf.size < frames
                if not needs_audio:
                    break
                try:
                    data, cb = self.audio_queue.get_nowait()
                    if cb:
                        threading.Thread(target=cb, daemon=True).start()
                    
                    with self._lock:
                        self._state.buf = np.concatenate([self._state.buf, np.asarray(data, dtype=np.float32).reshape(-1)])
                except queue.Empty:
                    break

            with self._lock:
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
            except Exception as e:
                self._playback_error = e
                print(f"Playback Error: {e}")
                return
            
            if self.stop_event.is_set():
                time.sleep(0.1)

def speak_text(model, text, voice="Heart", sr=24000, stop_event=None, model_id=DEFAULT_TTS_MODEL_ID):
    """Legacy one-shot wrapper. Blocks until done."""
    speaker = BufferedSpeaker(model, voice, sr, model_id=model_id)
    speaker.feed(text)
    speaker.text_queue.put(None)
    while not speaker.is_idle():
        if stop_event and stop_event.is_set():
            speaker.stop()
            break
        time.sleep(0.1)
    speaker.wait_until_idle(timeout=5)
    speaker.stop()

if __name__ == "__main__":
    print(f"Internal TTS Supported: {INTERNAL_TTS_SUPPORTED}")
    if INTERNAL_TTS_SUPPORTED:
        print("Loading local model...")
        m = load_tts_model()
        s = BufferedSpeaker(m)
        s.feed("Test internal synthesis.")
    else:
        print("Internal MLX TTS is not available in this environment.")
