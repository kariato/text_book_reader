# Manual TTS Tests

These scripts are intentionally outside pytest because they can download large
MLX models, allocate significant memory, and write audio files.

Run the recommended-model bakeoff:

```bash
python manual_tests/tts_model_bakeoff.py
```

Run one model:

```bash
python manual_tests/tts_model_bakeoff.py --model kokoro
```

Run one model and play it immediately:

```bash
python manual_tests/tts_model_bakeoff.py --model kokoro --play
```

List available model cases:

```bash
python manual_tests/tts_model_bakeoff.py --list
```

Generated WAV files and `summary.json` are written to
`manual_tests/tts_bakeoff_output/` by default.

MLX/Hugging Face model downloads are stored under
`/Volumes/NVME/Source/tts/huggingface`.
