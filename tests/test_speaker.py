from sample_code.speaker import BufferedSpeaker, generation_kwargs


def test_speaker_initialization():
    speaker = BufferedSpeaker(model=None)

    assert speaker.model is None
    assert speaker.model_id == ""
    assert speaker.text_queue.empty()
    assert speaker.audio_queue.empty()


def test_speaker_feed_and_stop():
    speaker = BufferedSpeaker(model=None)

    speaker.feed("Hello world")
    speaker.stop()
    assert speaker.text_queue.empty()
    assert speaker.audio_queue.empty()


def test_speaker_set_model_updates_model_id():
    speaker = BufferedSpeaker(model=None)
    model = object()

    speaker.set_model(model, "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16", "Chelsie")

    assert speaker.model is model
    assert speaker.model_id == "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16"
    assert speaker.voice == "Chelsie"


def test_generation_kwargs_are_model_voice_specific():
    assert generation_kwargs("mlx-community/Kokoro-82M-bf16", "Heart")["voice"] == "af_heart"
    assert generation_kwargs("mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16", "Chelsie") == {
        "voice": "Chelsie",
        "lang_code": "English",
    }
    assert generation_kwargs("mlx-community/chatterbox-turbo-fp16", "Default") == {}


def test_speaker_wait_until_idle_with_missing_model():
    speaker = BufferedSpeaker(model=None)

    speaker.feed("Hello world")

    assert speaker.wait_until_idle(timeout=1)
