import pytest
import os
from pathlib import Path
from sample_code.reader import BookReader

def test_chapter_navigation(tmp_path):
    # Setup dummy scenes
    # ch01: sc1, sc2
    # ch02: sc1
    # ch03: sc1, sc2, sc3
    
    scenes_dir = tmp_path / "scenes"
    scenes_dir.mkdir()
    
    (scenes_dir / "ch01").mkdir()
    (scenes_dir / "ch01" / "01_01.md").write_text("# Scene 1-1\nText 1-1", encoding="utf-8")
    (scenes_dir / "ch01" / "01_02.md").write_text("# Scene 1-2\nText 1-2", encoding="utf-8")
    
    (scenes_dir / "ch02").mkdir()
    (scenes_dir / "ch02" / "02_01.md").write_text("# Scene 2-1\nText 2-1", encoding="utf-8")
    
    (scenes_dir / "ch03").mkdir()
    (scenes_dir / "ch03" / "03_01.md").write_text("# Scene 3-1\nText 3-1", encoding="utf-8")
    (scenes_dir / "ch03" / "03_02.md").write_text("# Scene 3-2\nText 3-2", encoding="utf-8")
    
    progress_file = tmp_path / "progress.json"
    reader = BookReader(scenes_dir, progress_file=progress_file)
    
    # Initial state: [1/6] ch1 sc1
    assert reader.current.chapter == 1
    assert reader.current.scene == 1
    
    # Next scene: [2/6] ch1 sc2
    reader.next_scene()
    assert reader.current.chapter == 1
    assert reader.current.scene == 2
    
    # Next chapter from ch1 sc2 -> ch2 sc1
    reader.next_chapter()
    assert reader.current.chapter == 2
    assert reader.current.scene == 1
    
    # Next chapter from ch2 sc1 -> ch3 sc1
    reader.next_chapter()
    assert reader.current.chapter == 3
    assert reader.current.scene == 1
    
    # Next chapter from ch3 sc1 -> None (at last chapter)
    assert reader.next_chapter() is None
    assert reader.current.chapter == 3
    
    # Prev scene from ch3 sc1 -> ch2 sc1 (since it's a scene navigation, it goes back in the flat list)
    reader.prev_scene()
    assert reader.current.chapter == 2
    assert reader.current.scene == 1
    
    # Go to ch3 sc2
    reader.go_to(3, 2)
    assert reader.current.chapter == 3
    assert reader.current.scene == 2
    
    # Prev chapter from ch3 sc2 -> ch3 sc1 (first scene of current chapter)
    reader.prev_chapter()
    assert reader.current.chapter == 3
    assert reader.current.scene == 1
    
    # Prev chapter from ch3 sc1 -> ch2 sc1 (first scene of previous chapter)
    reader.prev_chapter()
    assert reader.current.chapter == 2
    assert reader.current.scene == 1
    
    # Prev chapter from ch2 sc1 -> ch1 sc1
    reader.prev_chapter()
    assert reader.current.chapter == 1
    assert reader.current.scene == 1
    
    # Prev chapter from ch1 sc1 -> None
    assert reader.prev_chapter() is None
    assert reader.current.chapter == 1
    assert reader.current.scene == 1
