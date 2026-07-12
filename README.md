# Mythosyne TTS Reader Add-On

A local audiobook add-on for Mythosyne workflows. It opens a prepared chapter/scene manuscript folder, reads it aloud with MLX TTS, exports `.m4a` audio by chapter or by scene, and can merge those exports into one marked `.m4a` audiobook file.

## What It Does

- **Scene Reader**: Loads a folder of chapter and scene files, then lets you move through the manuscript while listening.
- **Local TTS Playback**: Uses MLX-compatible TTS models with selectable voices.
- **Chapter or Scene Export**: Generates `.m4a` files either one chapter at a time or one scene at a time.
- **Marked Audiobook Builder**: Combines exported `.m4a` files into one `.m4a` with a marker for each source file.
- **Bookmarks and Notes**: Saves reading progress, custom bookmarks, and scene notes alongside the selected book folder.

## Manuscript Folder Format

The reader expects a folder containing chapter folders with Markdown or plain-text scene files. Files are discovered recursively and sorted by chapter and scene number.

Recommended format:

```text
my_book/
  ch01/
    scene1.md
    scene2.md
  ch02/
    scene1.md
```

Also supported:

```text
my_book/
  Chapter 001 - Arrival/
    Chapter 001 Scene 001 - The Door.txt
    Chapter 001 Scene 002 - The Hall.txt
  Chapter 002 - Below/
    Chapter 002 Scene 001 - The Stairs.txt
```

Scene files may be `.md` or `.txt`. Markdown headings are used as scene titles when present. `notes.txt` is ignored as a sidecar notes file.

## Installation

1. Ensure [Miniforge](https://github.com/conda-forge/miniforge) is installed.
2. Create and activate the TTS environment:

```bash
conda env create -f environment.yml
conda activate tts
```

3. If the environment already exists, update Python dependencies:

```bash
pip install -r requirements.txt
```

Audio export and audiobook combining use `ffmpeg` and `ffprobe`, included in `environment.yml`.

Model downloads are stored under:

```text
/Volumes/NVME/Source/tts/huggingface
```

## GUI Workflow

Launch the reader:

```bash
python sample_code/gui_reader.py
```

Then:

1. Click **Select Scene Folder** and choose your prepared manuscript folder.
2. Choose a TTS model and voice.
3. Use **Start**, **Stop**, and the chapter/scene navigation buttons to listen.
4. Choose **Export: Chapter** or **Export: Scene**.
5. Choose **Quality** from `32k` through `128k` in 16k steps. Lower values make smaller voice files; higher values preserve more detail.
6. Click **Export Audio** and choose an output directory.
7. Click **Combine M4A** to merge exported files into one marked audiobook `.m4a`.

## Export Formats

Chapter export creates one file per chapter:

```text
Chapter_001.m4a
Chapter_002.m4a
Chapter_003.m4a
```

Scene export creates one file per scene:

```text
Chapter_001_Scene_001.m4a
Chapter_001_Scene_002.m4a
Chapter_002_Scene_001.m4a
```

**Combine M4A** reads those filenames in numeric order and creates one `.m4a` with markers named from the source files, such as `Chapter 1` or `Chapter 1, Scene 2`.

Export quality controls the AAC bitrate passed to ffmpeg:

```text
32k, 48k, 64k, 80k, 96k, 112k, 128k
```

The default is `64k`, which is a compact voice-friendly setting.

## CLI Reader

For terminal playback:

```bash
python sample_code/book_reader.py path/to/my_book
```

Controls:

- `Enter`: Next scene
- `p`: Previous scene
- `s`: Skip current audio
- `q`: Quit and save position

## Optional Text Import

The GUI still includes **Import Text Book** for splitting a plain `.txt` manuscript into the chapter/scene folder format. For Mythosyne use, the preferred path is to generate or maintain the chapter/scene folder directly.

## Testing

Run the test suite:

```bash
pytest tests/
```
