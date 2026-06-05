"""Load Kokoro and print generated audio chunk metadata."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sample_code.speaker import load_tts_model


def main() -> int:
    print("Loading model...")
    model = load_tts_model("mlx-community/Kokoro-82M-bf16")
    if model is None:
        print("MLX TTS is not available in this environment.")
        return 1

    print("Model loaded. Generating...")
    for result in model.generate("Hello world", voice="af_heart"):
        print("Got result type:", type(result))
        if hasattr(result, "audio"):
            print("Audio shape:", len(result.audio))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
