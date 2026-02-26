"""
reader.py — BookReader: scene loading, navigation, and progress persistence.

Scene directory layout expected:
    scenes/
        ch01/
            scene1.md
            scene2.md
        ch02/
            scene1.md
        …

Each .md file has a `# Title` first line, followed by body text.
"""

import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------

_MD_HEADING     = re.compile(r"^#{1,6}\s+")          # # Heading
_MD_ITALIC_BOLD = re.compile(r"(\*{1,3}|_{1,3})(.*?)\1")  # *italic* / **bold**
_GUTENBERG_TAG  = re.compile(r"\[Illustration.*?\]", re.IGNORECASE)
_UNDERSCORE_EM  = re.compile(r"_([^_]+)_")           # _emphasis_  →  emphasis
_STAGE_DIR      = re.compile(r"_\[.*?\]_", re.DOTALL) # _[stage directions]_
_PAREN_MEM      = re.compile(r"\(_Mem\._.*?\)", re.IGNORECASE)


def _clean_text(raw: str) -> str:
    """
    Strip markdown and Gutenberg formatting artefacts, returning plain prose
    suitable for TTS.
    """
    lines = []
    for line in raw.splitlines():
        line = _MD_HEADING.sub("", line)
        line = _GUTENBERG_TAG.sub("", line)
        line = _STAGE_DIR.sub("", line)
        line = _PAREN_MEM.sub("", line)
        line = _MD_ITALIC_BOLD.sub(r"\2", line)
        line = _UNDERSCORE_EM.sub(r"\1", line)
        # Collapse em-dash markers like "_3 May. Bistritz._--" into clean text
        line = re.sub(r"--+", " — ", line)
        # Remove leftover underscores
        line = line.replace("_", "")
        lines.append(line)

    text = "\n".join(lines)
    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


# ---------------------------------------------------------------------------
# Scene index entry
# ---------------------------------------------------------------------------

class Scene:
    def __init__(self, path: Path, chapter: int, scene: int):
        self.path    = path
        self.chapter = chapter
        self.scene   = scene

    @property
    def label(self) -> str:
        return f"Chapter {self.chapter}, Scene {self.scene}"

    def title(self) -> str:
        """Return the markdown heading from the first line of the file."""
        with open(self.path, encoding="utf-8") as f:
            first = f.readline().strip()
        return first.lstrip("#").strip() or self.label

    def text(self) -> str:
        """Return clean plain-text content suitable for TTS."""
        raw = self.path.read_text(encoding="utf-8")
        return _clean_text(raw)

    def __repr__(self):
        return f"Scene(ch={self.chapter}, sc={self.scene}, path={self.path.name})"


# ---------------------------------------------------------------------------
# BookReader
# ---------------------------------------------------------------------------

class BookReader:
    """
    Loads all scenes from a scenes directory, handles navigation,
    and persists reading position to a JSON file.
    """

    DEFAULT_PROGRESS_FILE = Path.home() / ".book_reader_progress.json"

    def __init__(self, scenes_dir: str | Path, progress_file: Path | None = None):
        self.scenes_dir    = Path(scenes_dir)
        self.progress_file = progress_file or self.DEFAULT_PROGRESS_FILE
        self._scenes: list[Scene] = []
        self._index: int = 0   # current position in the flat scene list

        self._load_scenes()
        self._restore_progress()

    # ------------------------------------------------------------------
    # Scene discovery
    # ------------------------------------------------------------------

    def _load_scenes(self) -> None:
        """Scan scenes_dir and build a sorted flat list of Scene objects."""
        if not self.scenes_dir.exists():
            print(f"ERROR: scenes directory not found: {self.scenes_dir}", file=sys.stderr)
            sys.exit(1)

        scenes: list[Scene] = []
        for ch_dir in sorted(self.scenes_dir.iterdir()):
            if not ch_dir.is_dir():
                continue
            m = re.match(r"ch(\d+)", ch_dir.name)
            if not m:
                continue
            ch_num = int(m.group(1))

            for sc_file in sorted(
                ch_dir.glob("scene*.md"),
                key=lambda p: int(re.search(r"\d+", p.stem).group()),
            ):
                sc_m = re.match(r"scene(\d+)", sc_file.stem)
                if sc_m:
                    scenes.append(Scene(sc_file, ch_num, int(sc_m.group(1))))

        if not scenes:
            print(f"ERROR: no scene files found in {self.scenes_dir}", file=sys.stderr)
            sys.exit(1)

        self._scenes = scenes
        print(f"Loaded {len(scenes)} scenes across {self._chapter_count()} chapters.")

    def _chapter_count(self) -> int:
        return len({s.chapter for s in self._scenes})

    # ------------------------------------------------------------------
    # Progress persistence
    # ------------------------------------------------------------------

    def _restore_progress(self) -> None:
        """Load saved position from JSON if it exists."""
        if not self.progress_file.exists():
            return
        try:
            data = json.loads(self.progress_file.read_text())
            book_key = str(self.scenes_dir.resolve())
            if data.get("book") == book_key and "index" in data:
                idx = int(data["index"])
                if 0 <= idx < len(self._scenes):
                    self._index = idx
                    print(f"Resuming from: {self.current.label} — {self.current.title()}")
        except Exception:
            pass  # corrupt progress file — start from beginning

    def save_progress(self) -> None:
        """Persist current position to JSON."""
        data = {
            "book":  str(self.scenes_dir.resolve()),
            "index": self._index,
            "label": self.current.label,
        }
        self.progress_file.write_text(json.dumps(data, indent=2))

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    @property
    def current(self) -> Scene:
        return self._scenes[self._index]

    @property
    def has_next(self) -> bool:
        return self._index < len(self._scenes) - 1

    @property
    def has_prev(self) -> bool:
        return self._index > 0

    def next_scene(self) -> Scene | None:
        if self.has_next:
            self._index += 1
            self.save_progress()
            return self.current
        return None

    def prev_scene(self) -> Scene | None:
        if self.has_prev:
            self._index -= 1
            self.save_progress()
            return self.current
        return None

    def go_to(self, chapter: int, scene: int) -> Scene | None:
        """Jump to a specific chapter/scene. Returns the Scene or None if not found."""
        for i, s in enumerate(self._scenes):
            if s.chapter == chapter and s.scene == scene:
                self._index = i
                self.save_progress()
                return self.current
        return None

    def position_info(self) -> str:
        total = len(self._scenes)
        return f"[{self._index + 1}/{total}] {self.current.label}"
