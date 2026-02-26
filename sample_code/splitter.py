#!/usr/bin/env python3
"""
book_splitter.py — Split a plain-text Project Gutenberg book into per-scene Markdown files.

Supports two common formats:
  • Chapter-based novels  — lines exactly matching "CHAPTER I", "CHAPTER II", …
                            (no trailing subtitle on the same line)
  • Act/Scene-based plays — "ACT I", "ACT II", …

Within each chapter, journal-entry date stamps (e.g. "_3 May. Bistritz._--")
are used as scene boundaries. If none are found, the whole chapter becomes scene1.md.

Output layout:
  <output_dir>/
    ch01/
      scene1.md
      scene2.md
    ch02/
      scene1.md
    …

Usage:
  python sample.py [book_file] [output_dir]

  book_file  — path to the plain-text book  (default: sample_book/dracula.txt)
  output_dir — where to write scene files   (default: sample_book/scenes)
"""

import re
import sys
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Matches a REAL chapter heading: "CHAPTER I" or "CHAPTER XIV" — number only, no subtitle.
# The line must consist of nothing else after the roman numeral / digit.
RE_CHAPTER = re.compile(
    r"^CHAPTER\s+([IVXLCDM]+|\d+)\s*$",
    re.IGNORECASE,
)

# ToC entries look like "CHAPTER I. Jonathan Harker's Journal" — skip these.
RE_CHAPTER_TOC = re.compile(
    r"^CHAPTER\s+([IVXLCDM]+|\d+)\s*[.\-—]",
    re.IGNORECASE,
)

# Matches ACT headings: "ACT I", "ACT II", "ACT 1" — number only on line.
RE_ACT = re.compile(
    r"^ACT\s+([IVXLCDM]+|\d+)\s*$",
    re.IGNORECASE,
)

# ToC-style act entries: " ACT I." with leading whitespace or trailing punctuation.
RE_ACT_TOC = re.compile(
    r"^\s+ACT\s|^ACT\s+([IVXLCDM]+|\d+)\s*\.",
    re.IGNORECASE,
)

# Journal date scene boundary: lines like "_3 May. Bistritz._--" or "_5 May._--"
RE_JOURNAL_DATE = re.compile(
    r"^_\d",
)

# Gutenberg preamble / postamble markers
RE_START = re.compile(r"\*{3}\s*START OF THE PROJECT GUTENBERG", re.IGNORECASE)
RE_END   = re.compile(r"\*{3}\s*END OF THE PROJECT GUTENBERG",   re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def roman_to_int(s: str) -> Optional[int]:
    """Convert a Roman numeral string to an integer, or return None."""
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    s = s.strip().upper()
    if not all(c in vals for c in s):
        return None
    total, prev = 0, 0
    for ch in reversed(s):
        cur = vals[ch]
        total += cur if cur >= prev else -cur
        prev = cur
    return total


def parse_num(s: str) -> int:
    """Parse chapter/act number from a Roman numeral or digit string."""
    s = s.strip()
    if s.isdigit():
        return int(s)
    return roman_to_int(s) or 1


def strip_gutenberg(lines: list[str]) -> list[str]:
    """Return only the lines between the Gutenberg START and END markers."""
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
    """Strip leading/trailing blank lines and join as a string."""
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def write_scene(path: Path, title: str, content: str) -> None:
    """Write a scene file as Markdown."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        f.write(content)
        f.write("\n")
    print(f"  → {path}")


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def detect_format(lines: list[str]) -> str:
    """Return 'chapter', 'act', or 'unknown'."""
    chapters = sum(1 for l in lines if RE_CHAPTER.match(l.rstrip()) and not RE_CHAPTER_TOC.match(l.rstrip()))
    acts     = sum(1 for l in lines if RE_ACT.match(l.rstrip()) and not RE_ACT_TOC.match(l.rstrip()))
    if chapters >= acts and chapters > 0:
        return "chapter"
    if acts > 0:
        return "act"
    return "unknown"


# ---------------------------------------------------------------------------
# Scene splitting within a chapter body
# ---------------------------------------------------------------------------

def split_into_scenes(ch_num: int, ch_title: str, lines: list[str]) -> list[tuple[str, list[str]]]:
    """
    Split a chapter body by journal-date markers (e.g. "_3 May. Bistritz._--").
    Returns list of (scene_title, lines).
    Falls back to a single scene if no markers are found.
    """
    scenes: list[tuple[str, list[str]]] = []
    current_title = ch_title
    current_lines: list[str] = []

    for line in lines:
        raw = line.rstrip()
        if RE_JOURNAL_DATE.match(raw):
            if current_lines:
                scenes.append((current_title, list(current_lines)))
            # Use the date line (up to "--") as the scene title
            title_text = raw.lstrip("_").split("_")[0].rstrip(".").strip()
            current_title = f"{ch_title} — {title_text}" if title_text else ch_title
            current_lines = [raw]
        else:
            current_lines.append(raw)

    if current_lines:
        scenes.append((current_title, list(current_lines)))

    # If no date scenes found, return whole chapter as one scene
    if not scenes or (len(scenes) == 1 and scenes[0][0] == ch_title and not RE_JOURNAL_DATE.match(lines[0].rstrip() if lines else "")):
        return [(ch_title, [l.rstrip() for l in lines])]

    return scenes


# ---------------------------------------------------------------------------
# Chapter-based split
# ---------------------------------------------------------------------------

def split_chapters(lines: list[str], output_dir: Path) -> None:
    """Split a chapter-based novel into ch<NN>/scene<N>.md files."""

    # First pass: collect (chapter_num, chapter_title, [body_lines])
    chapters: list[tuple[int, str, list[str]]] = []
    current_lines: list[str] = []
    current_num = 0
    current_title = ""
    in_chapter = False

    for line in lines:
        raw = line.rstrip()
        stripped = raw.strip()

        # Is this a real chapter heading (not a ToC entry)?
        m = RE_CHAPTER.match(stripped)
        if m and not RE_CHAPTER_TOC.match(stripped):
            if in_chapter:
                chapters.append((current_num, current_title, current_lines))
            current_num   = parse_num(m.group(1))
            current_title = stripped  # e.g. "CHAPTER I"
            current_lines = []
            in_chapter    = True
        else:
            if in_chapter:
                current_lines.append(raw)

    if in_chapter and current_lines:
        chapters.append((current_num, current_title, current_lines))

    print(f"Found {len(chapters)} chapters.")

    for ch_num, ch_title, ch_lines in chapters:
        ch_dir = output_dir / f"ch{ch_num:02d}"
        scenes = split_into_scenes(ch_num, ch_title, ch_lines)

        for sc_idx, (sc_title, sc_lines) in enumerate(scenes, start=1):
            content = clean_block(list(sc_lines))
            write_scene(ch_dir / f"scene{sc_idx}.md", sc_title or ch_title, content)


# ---------------------------------------------------------------------------
# Act-based split
# ---------------------------------------------------------------------------

def split_acts(lines: list[str], output_dir: Path) -> None:
    """Split an act-based play into ch<NN>/scene1.md files (one scene per act)."""

    acts: list[tuple[int, str, list[str]]] = []
    current_lines: list[str] = []
    current_num = 0
    current_title = ""
    in_act = False

    for line in lines:
        raw = line.rstrip()
        stripped = raw.strip()

        m = RE_ACT.match(stripped)
        if m and not RE_ACT_TOC.match(raw):  # check raw for leading whitespace
            if in_act:
                acts.append((current_num, current_title, current_lines))
            current_num   = parse_num(m.group(1))
            current_title = stripped
            current_lines = []
            in_act        = True
        else:
            if in_act:
                current_lines.append(raw)

    if in_act and current_lines:
        acts.append((current_num, current_title, current_lines))

    print(f"Found {len(acts)} acts.")

    for act_num, act_title, act_lines in acts:
        content = clean_block(list(act_lines))
        write_scene(output_dir / f"ch{act_num:02d}" / "scene1.md", act_title, content)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def split_book(book_path: str, output_dir: str) -> None:
    book_file = Path(book_path)
    out_dir   = Path(output_dir)

    if not book_file.exists():
        print(f"ERROR: File not found: {book_file}")
        sys.exit(1)

    print(f"Reading: {book_file}")
    with open(book_file, encoding="utf-8", errors="replace") as f:
        raw_lines = f.readlines()

    lines = strip_gutenberg(raw_lines)
    if not lines:
        print("WARNING: No Gutenberg markers found — using full file.")
        lines = [l.rstrip("\n") for l in raw_lines]

    fmt = detect_format(lines)
    print(f"Detected format : {fmt}")
    print(f"Output directory: {out_dir}\n")

    if fmt == "chapter":
        split_chapters(lines, out_dir)
    elif fmt == "act":
        split_acts(lines, out_dir)
    else:
        print("Unknown format — writing entire book as ch01/scene1.md")
        content = clean_block([l.rstrip() for l in lines])
        write_scene(out_dir / "ch01" / "scene1.md", book_file.stem, content)

    print("\nDone!")


if __name__ == "__main__":
    book = sys.argv[1] if len(sys.argv) > 1 else "sample_book/dracula.txt"
    dest = sys.argv[2] if len(sys.argv) > 2 else "sample_book/scenes"
    split_book(book, dest)