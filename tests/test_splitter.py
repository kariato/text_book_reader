import pytest
from sample_code.splitter import detect_format, parse_num, roman_to_int

def test_roman_to_int():
    assert roman_to_int("I") == 1
    assert roman_to_int("IV") == 4
    assert roman_to_int("X") == 10
    assert roman_to_int("XIV") == 14
    assert roman_to_int("XXVII") == 27
    assert roman_to_int("MCMXCIV") == 1994

def test_parse_num():
    assert parse_num("1") == 1
    assert parse_num("XIV") == 14
    assert parse_num("Invalid") == 1

def test_detect_format():
    chapter_text = ["CHAPTER I", "Some text", "CHAPTER II"]
    assert detect_format(chapter_text) == "chapter"
    
    act_text = ["ACT I", "SCENE 1", "ACT II"]
    assert detect_format(act_text) == "act"
    
    unknown = ["Just a normal book", "No markers here"]
    assert detect_format(unknown) == "unknown"

def test_toc_filtering():
    # Real chapter (exact match)
    from sample_code.splitter import RE_CHAPTER, RE_CHAPTER_TOC
    
    real = "CHAPTER I"
    toc = "CHAPTER I. Jonathan Harker’s Journal"
    
    assert RE_CHAPTER.match(real)
    assert not RE_CHAPTER_TOC.match(real)
    
    # RE_CHAPTER should NOT match the TOC one if it's strict
    assert not RE_CHAPTER.match(toc)
    assert RE_CHAPTER_TOC.match(toc)
