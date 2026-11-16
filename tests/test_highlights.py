import numpy as np

from clipador.highlights import find_highlights, loudness_highlights
from clipador.models import Transcript


def _loudness_with_peak(duration=60, peak=(30, 40)):
    loud = np.full(duration, 0.05)
    loud[peak[0]:peak[1]] = 0.8
    return loud


def test_heuristic_picks_the_loud_impactful_window(transcript):
    found = find_highlights(
        transcript, _loudness_with_peak(), num_clips=2, min_len=15, max_len=30, use_claude=False
    )
    best = found[0]
    assert best.source == "heuristica"
    assert best.start <= 35 <= best.end, "o clipe mais forte deve conter o trecho barulhento"
    assert best.score == 100.0
    assert "absurdo" in best.title.lower() or best.title


def test_clips_do_not_overlap_and_respect_length(transcript):
    found = find_highlights(
        transcript, _loudness_with_peak(), num_clips=3, min_len=15, max_len=30, use_claude=False
    )
    assert 1 <= len(found) <= 3
    ordered = sorted(found, key=lambda h: h.start)
    for a, b in zip(ordered, ordered[1:]):
        assert a.end <= b.start
    for h in found:
        assert 14 <= h.duration <= 31


def test_short_video_still_returns_a_clip():
    from tests.conftest import make_transcript

    short = make_transcript(duration=10)
    found = find_highlights(short, np.full(10, 0.1), num_clips=3, min_len=20, max_len=55, use_claude=False)
    assert len(found) == 1
    assert found[0].duration <= 10.5


def test_no_speech_falls_back_to_loudness():
    empty = Transcript("?", 120.0, [])
    loud = np.full(120, 0.02)
    loud[70:95] = 0.9
    found = find_highlights(empty, loud, num_clips=2, min_len=20, max_len=40, use_claude=False)
    assert found and found[0].source == "audio"
    assert found[0].start <= 80 <= found[0].end


def test_loudness_highlights_short_video_returns_whole():
    found = loudness_highlights(np.full(30, 0.1), 30.0, num_clips=3, min_len=20, max_len=55)
    assert len(found) == 1 and found[0].start == 0.0 and found[0].end == 30.0
