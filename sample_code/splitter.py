#!/usr/bin/env python3
"""
book_splitter.py — Split a plain-text Project Gutenberg book into per-scene Markdown files.
"""

import re
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

RE_CHAPTER = re.compile(r"^CHAPTER\s+([IVXLCDM]+|\d+)\s*$", re.IGNORECASE)
RE_CHAPTER_TOC = re.compile(r"^CHAPTER\s+([IVXLCDM]+|\d+)\s*[.\-—]", re.IGNORECASE)
RE_ACT = re.compile(r"^ACT\s+([IVXLCDM]+|\d+)\s*$", re.IGNORECASE)
RE_ACT_TOC = re.compile(r"^\s+ACT\s|^ACT\s+([IVXLCDM]+|\d+)\s*\.", re.IGNORECASE)
RE_JOURNAL_DATE = re.compile(r"^_\d")
RE_START = re.compile(r"\*{3}\s*START OF THE PROJECT GUTENBERG", re.IGNORECASE)
RE_END   = re.compile(r"\*{3}\s*END OF THE PROJECT GUTENBERG",   re.IGNORECASE)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def roman_to_int(s: str) -> Optional[int]:
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    s = s.strip().upper()
    if not all(c in vals for c in s): return None
    total, prev = 0, 0
    for ch in reversed(s):
        cur = vals[ch]
        total += cur if cur >= prev else -cur
        prev = cur
    return total

def parse_num(s: str) -> int:
    s = s.strip()
    if s.isdigit(): return int(s)
    return roman_to_int(s) or 1

def strip_gutenberg(lines: list[str]) -> list[str]:
    start_idx, end_idx = 0, len(lines)
    for i, line in enumerate(lines):
        if RE_START.search(line):
            start_idx = i + 1
            break
    for i in range(len(lines) - 1, start_idx, -1):
        if RE_END.search(lines[i]):
            end_idx = i
            break
    return lines[start_idx:end_idx]

def clean_block(lines: list[str]) -> str:
    while lines and not lines[0].strip(): lines.pop(0)
    while lines and not lines[-1].strip(): lines.pop()
    return "\n".join(lines)

def write_scene(path: Path, title: str, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        f.write(content)
        f.write("\n")

def detect_format(lines: list[str]) -> str:
    chapters = sum(1 for l in lines if RE_CHAPTER.match(l.rstrip()) and not RE_CHAPTER_TOC.match(l.rstrip()))
    acts     = sum(1 for l in lines if RE_ACT.match(l.rstrip()) and not RE_ACT_TOC.match(l.rstrip()))
    if chapters >= acts and chapters > 0: return "chapter"
    if acts > 0: return "act"
    return "unknown"

def split_into_scenes(ch_num: int, ch_title: str, lines: list[str]) -> list[tuple[str, list[str]]]:
    scenes: list[tuple[str, list[str]]] = []
    current_title = ch_title
    current_lines: list[str] = []

    for line in lines:
        raw = line.rstrip()
        if RE_JOURNAL_DATE.match(raw):
            if current_lines:
                scenes.append((current_title, list(current_lines)))
            title_text = raw.lstrip("_").split("_")[0].rstrip(".").strip()
            current_title = f"{ch_title} — {title_text}" if title_text else ch_title
            current_lines = [raw]
        else:
            current_lines.append(raw)

    if current_lines:
        scenes.append((current_title, list(current_lines)))

    if not scenes or (len(scenes) == 1 and scenes[0][0] == ch_title and not RE_JOURNAL_DATE.match(lines[0].rstrip() if lines else "")):
        return [(ch_title, [l.rstrip() for l in lines])]
    return scenes

# ---------------------------------------------------------------------------
# BookSplitter Class
# ---------------------------------------------------------------------------

class BookSplitter:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose

    def _log(self, msg: str):
        if self.verbose: print(msg)

    def split_book(self, book_path: str | Path, output_dir: str | Path) -> Path:
        book_file = Path(book_path)
        out_dir = Path(output_dir)

        if not book_file.exists():
            raise FileNotFoundError(f"Book file not found: {book_file}")

        self._log(f"Reading: {book_file}")
        with open(book_file, encoding="utf-8", errors="replace") as f:
            raw_lines = f.readlines()

        lines = strip_gutenberg(raw_lines)
        if not lines:
            self._log("WARNING: No Gutenberg markers found — using full file.")
            lines = [l.rstrip("\n") for l in raw_lines]

        fmt = detect_format(lines)
        self._log(f"Detected format : {fmt}")

        if fmt == "chapter":
            self._split_chapters(lines, out_dir)
        elif fmt == "act":
            self._split_acts(lines, out_dir)
        else:
            self._log("Unknown format — writing as ch01/scene1.md")
            content = clean_block([l.rstrip() for l in lines])
            write_scene(out_dir / "ch01" / "scene1.md", book_file.stem, content)

        self._log(f"Done! Scenes written to {out_dir}")
        return out_dir.resolve()

    def _split_chapters(self, lines: list[str], output_dir: Path) -> None:
        chapters: list[tuple[int, str, list[str]]] = []
        current_lines, current_num, current_title, in_chapter = [], 0, "", False

        for line in lines:
            raw = line.rstrip(); stripped = raw.strip()
            m = RE_CHAPTER.match(stripped)
            if m and not RE_CHAPTER_TOC.match(stripped):
                if in_chapter: chapters.append((current_num, current_title, current_lines))
                current_num, current_title, current_lines, in_chapter = parse_num(m.group(1)), stripped, [], True
            elif in_chapter:
                current_lines.append(raw)

        if in_chapter and current_lines: chapters.append((current_num, current_title, current_lines))
        self._log(f"Found {len(chapters)} chapters.")

        for ch_num, ch_title, ch_lines in chapters:
            ch_dir = output_dir / f"ch{ch_num:02d}"
            scenes = split_into_scenes(ch_num, ch_title, ch_lines)
            for sc_idx, (sc_title, sc_lines) in enumerate(scenes, start=1):
                write_scene(ch_dir / f"scene{sc_idx}.md", sc_title or ch_title, clean_block(list(sc_lines)))

    def _split_acts(self, lines: list[str], output_dir: Path) -> None:
        acts: list[tuple[int, str, list[str]]] = []
        current_lines, current_num, current_title, in_act = [], 0, "", False

        for line in lines:
            raw = line.rstrip(); stripped = raw.strip()
            m = RE_ACT.match(stripped)
            if m and not RE_ACT_TOC.match(raw):
                if in_act: acts.append((current_num, current_title, current_lines))
                current_num, current_title, current_lines, in_act = parse_num(m.group(1)), stripped, [], True
            elif in_act:
                current_lines.append(raw)

        if in_act and current_lines: acts.append((current_num, current_title, current_lines))
        self._log(f"Found {len(acts)} acts.")

        for act_num, act_title, act_lines in acts:
            write_scene(output_dir / f"ch{act_num:02d}" / "scene1.md", act_title, clean_block(list(act_lines)))

if __name__ == "__main__":
    import sys
    book = sys.argv[1] if len(sys.argv) > 1 else "sample_book/dracula.txt"
    dest = sys.argv[2] if len(sys.argv) > 2 else "sample_book/scenes"
    BookSplitter().split_book(book, dest)