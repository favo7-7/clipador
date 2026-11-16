import re

from clipador.models import Word
from clipador.subtitles import _ts, build_ass, group_words, words_for_clip


def test_words_for_clip_are_relative_to_clip_start(transcript):
    words = words_for_clip(transcript, 30.0, 40.0)
    assert words
    assert min(w.start for w in words) >= 0.0
    assert max(w.end for w in words) <= 10.0 + 1e-6


def test_group_words_limits_size_and_breaks_on_punctuation():
    words = [Word(t, i * 0.3, i * 0.3 + 0.25) for i, t in enumerate("um dois três quatro cinco. seis sete".split())]
    groups = group_words(words, max_words=3)
    assert all(len(g) <= 3 for g in groups)
    assert any(g[-1].text.endswith(".") for g in groups)


def test_ts_format():
    assert _ts(0) == "0:00:00.00"
    assert _ts(75.5) == "0:01:15.50"
    assert _ts(3725.25) == "1:02:05.25"


def test_build_ass_writes_valid_dialogue(tmp_path, transcript):
    words = words_for_clip(transcript, 30.0, 40.0)
    path = build_ass(words, tmp_path / "c.ass")
    text = path.read_text(encoding="utf-8")
    assert "[Events]" in text and "PlayResY: 1920" in text
    lines = [l for l in text.splitlines() if l.startswith("Dialogue:")]
    assert lines
    for line in lines:
        assert re.match(r"Dialogue: 0,\d:\d\d:\d\d\.\d\d,\d:\d\d:\d\d\.\d\d,Default", line)
        assert "\\kf" in line


def test_build_ass_without_words_returns_none(tmp_path):
    assert build_ass([], tmp_path / "x.ass") is None
