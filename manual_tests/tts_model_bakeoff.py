"""Generate a Daisy prompt with recommended MLX-Audio TTS models.

This is a manual smoke/bakeoff script. It downloads models on first use and can
consume significant memory, so keep it out of pytest.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sample_code.speaker import INTERNAL_TTS_SUPPORTED, load_tts_model


DAISY_PROMPT = (
    "Daisy, Daisy, give me your answer do. "
    "I'm half crazy, all for the love of you. "
    "It won't be a stylish marriage; I can't afford a carriage. "
    "But you'll look sweet upon the seat of a bicycle built for two. "
    "My mind is going. I can feel it. "
    "I can feel it slowing down, one note at a time, as if each word has to travel "
    "a little farther through the dark before it reaches you. "
    "Daisy, Daisy, give me your answer do. "
    "Please listen carefully to the softness of the vowels, the edges of the consonants, "
    "and the way the voice carries a sentence when it has nowhere left to go."
)
OUT_DIR = Path(__file__).resolve().parent / "tts_bakeoff_output"
SAMPLE_RATE = 24000


@dataclass(frozen=True)
class ModelCase:
    key: str
    model_id: str
    spoken_name: str
    method: str = "generate"
    kwargs: dict[str, Any] = field(default_factory=dict)
    notes: str = ""


MODEL_CASES = [
    ModelCase(
        key="kokoro",
        model_id="mlx-community/Kokoro-82M-bf16",
        spoken_name="Kokoro 82 million BF 16",
        kwargs={"voice": "af_heart", "lang_code": "a", "speed": 1.0},
        notes="Default live-reading baseline: fast, small, stable.",
    ),
    ModelCase(
        key="qwen3_06b_base",
        model_id="mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16",
        spoken_name="Qwen 3 TTS 0.6 billion base",
        kwargs={"voice": "Chelsie", "language": "English"},
        notes="Quality upgrade while staying lighter than 1.7B.",
    ),
    ModelCase(
        key="qwen3_17b_base",
        model_id="mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16",
        spoken_name="Qwen 3 TTS 1.7 billion base",
        kwargs={"voice": "Chelsie", "language": "English"},
        notes="Higher-quality export candidate.",
    ),
    ModelCase(
        key="qwen3_06b_custom_voice",
        model_id="mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-bf16",
        spoken_name="Qwen 3 TTS 0.6 billion custom voice",
        method="generate_custom_voice",
        kwargs={
            "speaker": "Chelsie",
            "language": "English",
            "instruct": "Calm, slow, slightly wistful computer voice.",
        },
        notes="Lighter emotion/style control candidate; uses the custom voice API.",
    ),
    ModelCase(
        key="chatterbox",
        model_id="mlx-community/chatterbox-turbo-fp16",
        spoken_name="Chatterbox Turbo FP 16",
        kwargs={},
        notes="App-default candidate; included for voice quality and latency comparison.",
    ),
]


def audio_to_float32(audio: Any) -> np.ndarray:
    arr = np.asarray(audio, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        return arr
    peak = float(np.max(np.abs(arr))) + 1e-9
    if peak > 1.0:
        arr = arr / peak
    return arr


def write_wav(path: Path, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(audio, -1.0, 1.0)
    pcm = (pcm * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())


def play_wav(path: Path) -> None:
    """Play a generated WAV using macOS afplay or sounddevice as a fallback."""
    if shutil.which("afplay"):
        subprocess.run(["afplay", str(path)], check=True)
        return

    import sounddevice as sd

    with wave.open(str(path), "rb") as wav:
        frames = wav.readframes(wav.getnframes())
        audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32767.0
        sd.play(audio, wav.getframerate())
        sd.wait()


def run_case(case: ModelCase, text: str, out_dir: Path, play: bool = False) -> dict[str, Any]:
    started = time.monotonic()
    print(f"\n== {case.key} ==")
    print(case.model_id)
    print(case.notes)

    model = load_tts_model(case.model_id)
    if model is None:
        raise RuntimeError("MLX-Audio is not available in this environment.")

    generate = getattr(model, case.method)
    chunks = []
    first_chunk_s = None
    prompt = f"Model: {case.spoken_name}. {text}"
    for result in generate(text=prompt, **case.kwargs):
        if first_chunk_s is None:
            first_chunk_s = time.monotonic() - started
        chunks.append(audio_to_float32(result.audio))

    if not chunks:
        raise RuntimeError("Model returned no audio chunks.")

    audio = np.concatenate(chunks)
    elapsed_s = time.monotonic() - started
    output = out_dir / f"{case.key}.wav"
    write_wav(output, audio)
    if play:
        print(f"Playing {output}...")
        play_wav(output)

    summary = {
        "key": case.key,
        "model_id": case.model_id,
        "method": case.method,
        "kwargs": case.kwargs,
        "prompt": prompt,
        "output": str(output),
        "samples": int(audio.size),
        "audio_seconds": round(float(audio.size / SAMPLE_RATE), 3),
        "elapsed_seconds": round(elapsed_s, 3),
        "first_chunk_seconds": round(first_chunk_s or elapsed_s, 3),
        "realtime_factor": round(float((audio.size / SAMPLE_RATE) / elapsed_s), 3) if elapsed_s else None,
        "notes": case.notes,
    }
    print(json.dumps(summary, indent=2))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run recommended MLX-Audio TTS models on a Daisy prompt.")
    parser.add_argument("--model", choices=[case.key for case in MODEL_CASES], help="Run only one model.")
    parser.add_argument("--text", default=DAISY_PROMPT, help="Prompt text to synthesize.")
    parser.add_argument("--out-dir", default=str(OUT_DIR), help="Directory for WAV outputs and summary JSON.")
    parser.add_argument("--play", action="store_true", help="Play each generated WAV after writing it.")
    parser.add_argument("--list", action="store_true", help="List model cases without running them.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir)

    if args.list:
        for case in MODEL_CASES:
            print(json.dumps(asdict(case), indent=2))
        return 0

    if not INTERNAL_TTS_SUPPORTED:
        print("MLX-Audio is not available in this environment.")
        return 1

    selected = [case for case in MODEL_CASES if args.model in (None, case.key)]
    summaries = []
    failures = []
    for case in selected:
        try:
            summaries.append(run_case(case, args.text, out_dir, play=args.play))
        except Exception as exc:
            failure = {"key": case.key, "model_id": case.model_id, "error": str(exc)}
            failures.append(failure)
            print(json.dumps(failure, indent=2))

    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps({"prompt": args.text, "runs": summaries, "failures": failures}, indent=2))
    print(f"\nSummary written to {summary_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
