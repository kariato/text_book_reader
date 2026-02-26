# Text Book Reader

A suite of tools to split Project Gutenberg texts into scenes and read them aloud using MLX-based streaming TTS.

## Features

-   **Book Splitter**: Automatically detects chapter/act structure and splits long text files into Markdown scene files.
-   **Terminal Reader**: CLI-based reader with session persistence and keyboard navigation.
-   **GUI Reader**: Tkinter-based application with folder selection, start/stop controls, and custom bookmark saving.
-   **Streaming TTS**: Low-latency audio synthesis using `mlx-community/chatterbox-turbo-fp16`.

## Installation

1.  Ensure you have [Miniforge](https://github.com/conda-forge/miniforge) installed.
2.  Create and activate the specialized TTS environment:
    ```bash
    conda create -n tts python=3.12
    conda activate tts
    ```
3.  Install dependencies:
    ```bash
    pip install mlx-audio sounddevice numpy pytest
    ```

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