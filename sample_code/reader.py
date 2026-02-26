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
        self._sentences: list[str] = []

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

    def sentences(self) -> list[str]:
        """Return the scene text split into sentences."""
        if not self._sentences:
            text = self.text()
            # Split on . ! ? followed by whitespace/newline, OR on multiple newlines
            # We use a lookbehind to keep the punctuation
            raw_sents = re.split(r'(?<=[.!?])\s+|\n+', text)
            self._sentences = [s.strip() for s in raw_sents if s.strip()]
        return self._sentences

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
        self._sentence_index: int = 0  # position within the current scene

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

    def _restore_progress(self, file_path: Path | None = None) -> bool:
        """Load saved position from JSON if it exists."""
        target = file_path or self.progress_file
        if not target.exists():
            return False
        try:
            data = json.loads(target.read_text())
            book_key = str(self.scenes_dir.resolve())
            if data.get("book") == book_key and "index" in data:
                self._index = int(data["index"])
                self._sentence_index = int(data.get("sentence_index", 0))
                print(f"Resuming from: {self.current.label} — {self.current.title()} (Sentence {self._sentence_index})")
                return True
        except Exception:
            pass  # corrupt progress file — start from beginning
        return False

    def save_progress(self, file_path: Path | None = None) -> None:
        """Persist current position to JSON."""
        target = file_path or self.progress_file
        data = {
            "book":  str(self.scenes_dir.resolve()),
            "index": self._index,
            "sentence_index": self._sentence_index,
            "label": self.current.label,
            "scene_title": self.current.title(),
        }
        target.write_text(json.dumps(data, indent=2))

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    @property
    def current(self) -> Scene:
        return self._scenes[self._index]

    @property
    def current_sentence_index(self) -> int:
        return self._sentence_index

    @current_sentence_index.setter
    def current_sentence_index(self, value: int):
        self._sentence_index = value

    @property
    def has_next(self) -> bool:
        # Has more sentences or has more scenes
        if self._sentence_index < len(self.current.sentences()) - 1:
            return True
        return self._index < len(self._scenes) - 1

    @property
    def has_prev(self) -> bool:
        if self._sentence_index > 0:
            return True
        return self._index > 0

    def next_sentence(self) -> str | None:
        """Advance to next sentence, moving to next scene if needed."""
        sents = self.current.sentences()
        if self._sentence_index < len(sents) - 1:
            self._sentence_index += 1
            return sents[self._sentence_index]
        elif self.has_next_scene():
            self.next_scene()
            return self.current.sentences()[0]
        return None

    def has_next_scene(self) -> bool:
        return self._index < len(self._scenes) - 1

    def next_scene(self) -> Scene | None:
        if self.has_next_scene():
            self._index += 1
            self._sentence_index = 0
            self.save_progress()
            return self.current
        return None

    def prev_scene(self) -> Scene | None:
        if self._index > 0:
            self._index -= 1
            self._sentence_index = 0
            self.save_progress()
            return self.current
        return None

    def go_to(self, chapter: int, scene: int, sentence: int = 0) -> Scene | None:
        """Jump to a specific chapter/scene/sentence. Returns the Scene or None if not found."""
        for i, s in enumerate(self._scenes):
            if s.chapter == chapter and s.scene == scene:
                self._index = i
                self._sentence_index = sentence
                self.save_progress()
                return self.current
        return None

    def position_info(self) -> str:
        total_sc = len(self._scenes)
        total_sent = len(self.current.sentences())
        return f"[{self._index + 1}/{total_sc}] {self.current.label} | Sent {self._sentence_index + 1}/{total_sent}"
