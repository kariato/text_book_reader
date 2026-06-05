"""Write 10 seconds of generated float32 noise through ffmpeg to verify export."""

import subprocess
from pathlib import Path

import numpy as np


def main() -> int:
    output = Path(__file__).resolve().parent / "test_out.m4a"
    cmd = [
        "ffmpeg", "-y",
        "-f", "f32le",
        "-ar", "24000",
        "-ac", "1",
        "-i", "pipe:0",
        "-c:a", "aac",
        "-b:a", "128k",
        str(output),
    ]

    process = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for _ in range(10):
            chunk = np.random.randn(24000).astype(np.float32) * 0.1
            if process.stdin:
                process.stdin.write(chunk.tobytes())
    finally:
        if process.stdin:
            process.stdin.close()

    return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
