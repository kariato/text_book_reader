# Text Book Reader

A suite of tools to split Project Gutenberg texts into scenes and read them aloud using MLX-based streaming TTS.

## Features

-   **Book Splitter**: Automatically detects chapter/act structure and splits long text files into Markdown scene files.
-   **Terminal Reader**: CLI-based reader with session persistence and keyboard navigation.
-   **GUI Reader**: Tkinter-based application with folder selection, start/stop controls, and custom bookmark saving.
-   **Streaming TTS**: MLX-based audio synthesis using Kokoro, Qwen3, and Chatterbox model options.

## Installation

1.  Ensure you have [Miniforge](https://github.com/conda-forge/miniforge) installed.
2.  Create and activate the specialized TTS environment:
    ```bash
    conda env create -f environment.yml
    conda activate tts
    ```
3.  If you already have the environment, update Python dependencies with:
    ```bash
    pip install -r requirements.txt
    ```

The GUI audio export uses `ffmpeg`, included in `environment.yml`.

Model downloads are stored under `/Volumes/NVME/Source/tts/huggingface`
instead of the default home-directory Hugging Face cache.

## Usage

### 1. Splitting a Book
Take a Project Gutenberg text (like `dracula.txt`) and split it into scenes:
```bash
python sample_code/splitter.py sample_book/dracula.txt sample_book/scenes
```

### 2. GUI Reader (Recommended)
Launch the graphical interface to browse scenes and listen:
```bash
python sample_code/gui_reader.py
```
-   Click **Select Book Folder** and point to `sample_book/scenes`.
-   Choose a TTS model and, where supported, a voice from the TTS Settings controls.
-   Choose **Export: Chapter** for one `.m4a` per chapter, or **Export: Scene** for one `.m4a` per scene.
-   Use **Combine M4A** to merge exported `.m4a` files into a single `.m4a` with one marker per source file.
-   Click **Test Voice** to generate and play the first 300 words of the loaded book; the GUI displays generation words per minute after synthesis.
-   Click **Start** to begin reading.
-   Use **Save Bookmark** to persist your exact position in a scene to a file.

### 3. CLI Reader
For terminal enthusiasts:
```bash
python sample_code/book_reader.py sample_book/scenes
```
-   `Enter`: Next scene
-   `p`: Previous scene
-   `s`: Skip current audio
-   `q`: Quit and save position

## Testing
Run the test suite using `pytest`:
```bash
pytest tests/
```
