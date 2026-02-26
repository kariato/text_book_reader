"""
speaker.py — Streaming TTS engine using MLX chatterbox.

Public API:
    load_tts_model(model_id)  -> model
    speak_text(model, text, voice, sr, stop_event) -> None
        Streams TTS audio to the speaker in real-time using a
        producer/consumer thread pair. Blocks until playback completes
        or stop_event is set.
"""

import threading
import queue
import time

import numpy as np
import sounddevice as sd
from mlx_audio.tts.utils import load_model


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def load_tts_model(model_id: str = "mlx-community/chatterbox-turbo-fp16"):
    """Load and return a chatterbox TTS model."""
    return load_model(model_id)


def speak_text(
    model,
    text: str,
    voice: str = "af_heart",
    sr: int = 24000,
    stop_event: threading.Event | None = None,
    blocksize: int = 2048,
) -> None:
    """
    Speak *text* aloud using streaming TTS. Blocks until playback finishes
    or stop_event is set.

    Args:
        model:       Loaded chatterbox TTS model.
        text:        Plain text to synthesise.
        voice:       Voice ID string (default: "af_heart").
        sr:          Sample rate in Hz (default: 24000).
        stop_event:  Optional threading.Event — set it to abort playback.
        blocksize:   sounddevice callback blocksize in frames.
    """
    if stop_event is None:
        stop_event = threading.Event()

    q: queue.Queue = queue.Queue(maxsize=8)  # backpressure keeps memory bounded

    producer = threading.Thread(
        target=_tts_producer,
        args=(model, text, voice, sr, q, stop_event),
        daemon=True,
    )
    consumer = threading.Thread(
        target=_audio_consumer,
        args=(sr, q, stop_event, blocksize),
        daemon=True,
    )

    consumer.start()
    producer.start()

    producer.join()
    consumer.join()


# ---------------------------------------------------------------------------
# Internal threads
# ---------------------------------------------------------------------------

def _tts_producer(
    model,
    text: str,
    voice: str,
    sr: int,
    q: queue.Queue,
    stop_event: threading.Event,
) -> None:
    """
    Generate TTS audio chunks and place them on the queue.
    Always puts None at the end to signal completion to the consumer.
    """
    try:
        for result in model.generate(text, voice=voice):
            if stop_event.is_set():
                break

            chunk = np.array(result.audio).squeeze().astype(np.float32)

            # Prevent clipping without full normalisation (avoids pumping artefact)
            peak = np.max(np.abs(chunk)) + 1e-9
            if peak > 1.0:
                chunk = chunk / peak

            # Block-with-timeout so we respect stop_event under backpressure
            while not stop_event.is_set():
                try:
                    q.put(chunk, timeout=0.1)
                    break
                except queue.Full:
                    continue
    finally:
        q.put(None)  # always signal end-of-stream


def _audio_consumer(
    sr: int,
    q: queue.Queue,
    stop_event: threading.Event,
    blocksize: int,
) -> None:
    """
    Pull audio chunks from the queue and play them via a sounddevice callback stream.
    """
    buf = np.zeros((0,), dtype=np.float32)

    def callback(outdata, frames, time_info, status):
        nonlocal buf

        out = np.zeros((frames,), dtype=np.float32)

        # Drain queue into internal buffer until we have enough frames
        while buf.size < frames and not stop_event.is_set():
            try:
                item = q.get_nowait()
            except queue.Empty:
                break
            if item is None:
                stop_event.set()
                break
            buf = np.concatenate([buf, np.asarray(item, dtype=np.float32).reshape(-1)])

        n = min(frames, buf.size)
        if n > 0:
            out[:n] = buf[:n]
            buf = buf[n:]

        outdata[:, 0] = out  # mono → channel 0

    with sd.OutputStream(
        samplerate=sr,
        channels=1,
        dtype="float32",
        blocksize=blocksize,
        callback=callback,
    ):
        while not stop_event.is_set():
            time.sleep(0.05)


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

def main():
    print("Loading model…")
    model = load_tts_model()
    stop = threading.Event()
    print("Speaking…")
    speak_text(model, "Hello! This is a test of the streaming TTS system.", stop_event=stop)
    print("Done.")


if __name__ == "__main__":
    main()