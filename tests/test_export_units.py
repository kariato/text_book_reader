from pathlib import Path
from types import SimpleNamespace

import pytest

from sample_code.gui_reader import (
    exported_m4a_files,
    exported_m4a_marker_title,
    export_units_for_scenes,
)


def scene(chapter, scene_num):
    return SimpleNamespace(chapter=chapter, scene=scene_num)


def test_export_units_group_by_chapter():
    scenes = [scene(1, 1), scene(1, 2), scene(2, 1)]

    units = export_units_for_scenes(scenes, "Chapter")

    assert [(label, filename) for label, filename, _ in units] == [
        ("Chapter 1", "Chapter_001.m4a"),
        ("Chapter 2", "Chapter_002.m4a"),
    ]
    assert [sc.scene for sc in units[0][2]] == [1, 2]
    assert [sc.scene for sc in units[1][2]] == [1]


def test_export_units_split_by_scene():
    scenes = [scene(1, 1), scene(1, 2), scene(2, 1)]

    units = export_units_for_scenes(scenes, "Scene")

    assert [(label, filename) for label, filename, _ in units] == [
        ("Chapter 1, Scene 1", "Chapter_001_Scene_001.m4a"),
        ("Chapter 1, Scene 2", "Chapter_001_Scene_002.m4a"),
        ("Chapter 2, Scene 1", "Chapter_002_Scene_001.m4a"),
    ]
    assert [[sc.scene for sc in unit_scenes] for _, _, unit_scenes in units] == [[1], [2], [1]]


def test_export_units_reject_unknown_mode():
    with pytest.raises(ValueError, match="Unsupported export mode"):
        export_units_for_scenes([scene(1, 1)], "Book")


def test_exported_m4a_files_use_export_order(tmp_path):
    names = [
        "Chapter_002_Scene_001.m4a",
        "Chapter_001_Scene_010.m4a",
        "Chapter_001_Scene_002.m4a",
        "Chapter_001_Scene_001.m4a",
        "notes.txt",
    ]
    for name in names:
        (tmp_path / name).write_text("", encoding="utf-8")

    files = exported_m4a_files(tmp_path)

    assert [path.name for path in files] == [
        "Chapter_001_Scene_001.m4a",
        "Chapter_001_Scene_002.m4a",
        "Chapter_001_Scene_010.m4a",
        "Chapter_002_Scene_001.m4a",
    ]


def test_exported_m4a_files_sort_chapter_exports(tmp_path):
    for name in ["Chapter_010.m4a", "Chapter_002.m4a", "Chapter_001.m4a"]:
        (tmp_path / name).write_text("", encoding="utf-8")

    files = exported_m4a_files(tmp_path)

    assert [path.name for path in files] == [
        "Chapter_001.m4a",
        "Chapter_002.m4a",
        "Chapter_010.m4a",
    ]


def test_exported_m4a_marker_title_uses_export_filename():
    assert exported_m4a_marker_title(Path("Chapter_001.m4a")) == "Chapter 1"
    assert exported_m4a_marker_title(Path("Chapter_001_Scene_002.m4a")) == "Chapter 1, Scene 2"
