import pytest
import json
from pathlib import Path
from sample_code.reader import BookReader, Scene, _clean_text

def test_clean_text():
    raw = "# Heading\n_italic_ and **bold**.\n[Illustration: tag]\n_3 May. Bistritz._--"
    cleaned = _clean_text(raw)
    assert "Heading" in cleaned
    assert "italic and bold" in cleaned
    assert "[Illustration" not in cleaned
    assert "Bistritz. —" in cleaned

def test_scene_sentences(tmp_path):
    # Mock a scene file
    content = "# Test\nThis is sentence one. This is sentence two! And three?"
    path = tmp_path / "test_scene.md"
    path.write_text(content, encoding="utf-8")
    
    scene = Scene(path, 1, 1)
    sents = scene.sentences()
    
    # Title "Test" should be its own sentence now
    assert len(sents) == 4
    assert sents[0] == "Test"
    assert sents[1] == "This is sentence one."
    assert sents[2] == "This is sentence two!"
    assert sents[3] == "And three?"

def test_reader_navigation(tmp_path):
    # Setup dummy scenes structure
    scenes_dir = tmp_path / "scenes"
    ch01 = scenes_dir / "ch01"
    ch01.mkdir(parents=True)
    (ch01 / "scene1.md").write_text("# S1\nText 1.", encoding="utf-8")
    (ch01 / "scene2.md").write_text("# S2\nText 2.", encoding="utf-8")
    
    reader = BookReader(scenes_dir, progress_file=tmp_path / "progress.json")
    
    assert reader.current.chapter == 1
    assert reader.current.scene == 1
    
    reader.next_sentence() # Advance sentence
    reader.next_sentence() # Should trigger next scene since S1 only has 1 sentence
    
    assert reader.current.scene == 2
    assert reader.current_sentence_index == 0

def test_reader_loads_nested_txt_scene_tree(tmp_path):
    book_dir = tmp_path / "si2" / "Spreading Insanity"
    ch02 = book_dir / "Chapter 002 - Boones Creek"
    ch01 = book_dir / "Chapter 001 - The Flight"
    ch02.mkdir(parents=True)
    ch01.mkdir(parents=True)

    (ch02 / "Chapter 002 Scene 002 - The Square.txt").write_text(
        "The square was quiet.", encoding="utf-8"
    )
    (ch01 / "Chapter 001 Scene 001 - Above The Fields.txt").write_text(
        "## Scene: Above the Fields\n\nThe helicopter thumped low.", encoding="utf-8"
    )
    (ch02 / "notes.txt").write_text("reader sidecar", encoding="utf-8")

    reader = BookReader(tmp_path / "si2", progress_file=tmp_path / "progress.json")

    assert len(reader._scenes) == 2
    assert reader.current.chapter == 1
    assert reader.current.scene == 1
    assert reader.current.title() == "Scene: Above the Fields"
    reader.next_scene()
    assert reader.current.chapter == 2
    assert reader.current.scene == 2
    assert reader.current.title() == "The Square"

def test_get_next_chunk_reads_single_sentence_book(tmp_path):
    scenes_dir = tmp_path / "scenes"
    ch01 = scenes_dir / "ch01"
    ch01.mkdir(parents=True)
    (ch01 / "scene1.md").write_text("# S1\nOnly sentence.", encoding="utf-8")

    reader = BookReader(scenes_dir, progress_file=tmp_path / "progress.json")

    assert reader.get_next_chunk() == "S1 Only sentence."
    assert reader.get_next_chunk() is None

def test_bookmark_persistence(tmp_path):
    scenes_dir = tmp_path / "scenes"
    ch01 = scenes_dir / "ch01"
    ch01.mkdir(parents=True)
    (ch01 / "scene1.md").write_text("# S1\nSentence one. Sentence two.", encoding="utf-8")
    
    progress_file = tmp_path / "progress.json"
    reader = BookReader(scenes_dir, progress_file=progress_file)
    
    reader.current_sentence_index = 1
    reader.save_progress()
    
    # Load in new reader
    reader2 = BookReader(scenes_dir, progress_file=progress_file)
    assert reader2.current_sentence_index == 1
    
    # Custom bookmark file
    bkm_file = tmp_path / "custom.json"
    reader.save_progress(bkm_file)
    assert bkm_file.exists()
    
    reader3 = BookReader(scenes_dir)
    reader3._restore_progress(bkm_file)
    assert reader3.current_sentence_index == 1
