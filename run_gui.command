#!/bin/bash

# Get the directory where this script is located
PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Path to the specialized TTS python environment
PYTHON_EXE="/Users/kariatoo/miniforge3/envs/tts/bin/python"
TTS_CACHE_ROOT="/Volumes/NVME/Source/tts"

export HF_HOME="$TTS_CACHE_ROOT/huggingface"
export HUGGINGFACE_HUB_CACHE="$HF_HOME/hub"
export HF_HUB_CACHE="$HF_HOME/hub"
export TRANSFORMERS_CACHE="$HF_HOME/transformers"

# Check if environment exists
if [ ! -f "$PYTHON_EXE" ]; then
    echo "ERROR: Python environment not found at $PYTHON_EXE"
    echo "Please ensure you have created the 'tts' conda environment."
    exit 1
fi

# Run the GUI reader
echo "Launching Book Reader GUI..."
cd "$PROJECT_DIR"
"$PYTHON_EXE" sample_code/gui_reader.py
