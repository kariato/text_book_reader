"""
book_reader.py — CLI entry point for the TTS book reader.

Usage:
    python book_reader.py [scenes_dir] [options]

Options:
    --voice VOICE       TTS voice ID        (default: af_heart)
    --chapter N         Start at chapter N  (default: resume or 1)
    --scene N           Start at scene N    (default: resume or 1)
    --model MODEL_ID    HuggingFace model   (default: mlx-community/chatterbox-turbo-fp16)

Controls during playback:
    Enter   →  Next scene
    p       →  Previous scene
    s       →  Skip (stop speaking, go to next)
    q       →  Quit and save position
    r       →  Repeat current scene
    ?       →  Show controls
"""

import argparse
import sys
import threading

# Allow running from anywhere by resolving sibling imports
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from reader  import BookReader
from speaker import load_tts_model, speak_text


# ---------------------------------------------------------------------------
# Keyboard input (non-blocking, cross-platform for macOS/Linux)
# ---------------------------------------------------------------------------

import termios, tty, select, os

def _getch_nonblocking() -> str | None:
    """Return a single character if one is available in stdin, else None."""
    if select.select([sys.stdin], [], [], 0)[0]:
        return sys.stdin.read(1)
    return None


def _get_command(prompt: bool = True) -> str:
    """
    Read a single keystroke from the terminal.
    Returns the character (lowercased).
    """
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch.lower()


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

CONTROLS = """
  Enter  → next scene
  p      → previous scene
  s      → skip (stop audio, next scene)
  r      → repeat current scene
  q      → quit and save position
  ?      → show this help
"""

def _print_separator():
    print("\n" + "─" * 60)

def _print_scene_header(reader: BookReader):
    _print_separator()
    print(f"  {reader.position_info()}")
    print(f"  {reader.current.title()}")
    _print_separator()


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------

def _speak_scene(model, reader: BookReader, voice: str, stop_event: threading.Event):
    """Speak the current scene. Blocks until done or stop_event is set."""
    text = reader.current.text()
    if not text.strip():
        print("  (empty scene, skipping)")
        return
    print(f"\n  Speaking… (s=skip, q=quit)\n")
    speak_text(model, text, voice=voice, stop_event=stop_event)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(scenes_dir: str, voice: str, model_id: str, start_chapter: int | None, start_scene: int | None):
    print("\n📖  Book Reader  📖")
    print("Loading scenes…")
    reader = BookReader(scenes_dir)

    # Jump to explicit start position if provided
    if start_chapter is not None:
        sc = start_scene or 1
        result = reader.go_to(start_chapter, sc)
        if result is None:
            print(f"WARNING: Chapter {start_chapter} Scene {sc} not found — starting from beginning.")

    print("\nLoading TTS model (this may take a moment)…")
    model = load_tts_model(model_id)
    print("Model ready.\n")

    print(CONTROLS)

    while True:
        _print_scene_header(reader)

        stop_event = threading.Event()

        # Speak in a background thread so we can accept keyboard input
        speech_thread = threading.Thread(
            target=_speak_scene,
            args=(model, reader, voice, stop_event),
            daemon=True,
        )
        speech_thread.start()

        # Wait for keypress while speech plays
        cmd = _get_command()

        if cmd in ("\r", "\n", ""):   # Enter → next
            stop_event.set()
            speech_thread.join()
            if reader.has_next:
                reader.next_scene()
            else:
                print("\n  🎉  End of book!")
                reader.save_progress()
                break

        elif cmd == "p":              # previous
            stop_event.set()
            speech_thread.join()
            if reader.has_prev:
                reader.prev_scene()
            else:
                print("\n  (already at the beginning)")

        elif cmd == "s":              # skip → next (same as Enter)
            stop_event.set()
            speech_thread.join()
            if reader.has_next:
                reader.next_scene()
            else:
                print("\n  🎉  End of book!")
                reader.save_progress()
                break

        elif cmd == "r":              # repeat
            stop_event.set()
            speech_thread.join()
            # stay on current scene, loop will re-speak it

        elif cmd == "q":              # quit
            stop_event.set()
            speech_thread.join()
            reader.save_progress()
            print("\n  Progress saved. Goodbye! 👋\n")
            break

        elif cmd == "?":              # help
            stop_event.set()
            speech_thread.join()
            print(CONTROLS)

        else:
            # Unknown key: let speech finish naturally, then wait for Enter
            speech_thread.join()
            if reader.has_next:
                reader.next_scene()
            else:
                print("\n  🎉  End of book!")
                reader.save_progress()
                break


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="TTS Book Reader — reads scenes from a scenes/ directory aloud.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=CONTROLS,
    )
    parser.add_argument(
        "scenes_dir",
        nargs="?",
        default="sample_book/scenes",
        help="Path to the scenes directory (default: sample_book/scenes)",
    )
    parser.add_argument("--voice",   default="af_heart",                           help="TTS voice ID")
    parser.add_argument("--model",   default="mlx-community/chatterbox-turbo-fp16", help="HuggingFace model ID")
    parser.add_argument("--chapter", type=int, default=None, help="Start at chapter N")
    parser.add_argument("--scene",   type=int, default=None, help="Start at scene N")

    args = parser.parse_args()

    run(
        scenes_dir=args.scenes_dir,
        voice=args.voice,
        model_id=args.model,
        start_chapter=args.chapter,
        start_scene=args.scene,
    )


if __name__ == "__main__":
    main()
