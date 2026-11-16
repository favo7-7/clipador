import json
import subprocess
from pathlib import Path

import pytest

from clipador import pipeline
from clipador.cutter import cut_clip
from clipador.pipeline import Options, process
from clipador.subtitles import build_ass, words_for_clip
from clipador.utils import ClipadorError, probe_duration


def _dimensions(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "csv=s=x:p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    w, h = out.split("x")
    return int(w), int(h)


@pytest.mark.parametrize("mode", ["fill", "blur"])
def test_cut_clip_makes_vertical_video_with_captions(sample_video, transcript, tmp_path, mode):
    ass = build_ass(words_for_clip(transcript, 28.0, 42.0), tmp_path / "c.ass")
    out = cut_clip(sample_video, tmp_path / f"{mode}.mp4", 28.0, 42.0, ass, mode=mode)
    assert _dimensions(out) == (1080, 1920)
    assert abs(probe_duration(out) - 14.0) < 0.6


def test_cut_clip_without_captions(sample_video, tmp_path):
    out = cut_clip(sample_video, tmp_path / "plain.mp4", 5.0, 15.0, None, mode="fill")
    assert _dimensions(out) == (1080, 1920)


def test_process_end_to_end_with_fake_transcription(sample_video, transcript, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "transcribe_video", lambda *a, **k: transcript)
    stages = []
    title, clips = process(
        sample_video, tmp_path / "out",
        Options(num_clips=2, min_len=15, max_len=30, use_claude=False),
        progress=lambda stage, frac, msg: stages.append((stage, frac)),
    )
    assert title == "sample"
    assert 1 <= len(clips) <= 2
    assert clips[0].start <= 35 <= clips[0].end
    for clip in clips:
        assert (tmp_path / "out" / "clips" / clip.file).is_file()
    data = json.loads((tmp_path / "out" / "clips.json").read_text(encoding="utf-8"))
    assert len(data["clips"]) == len(clips)
    fractions = [f for _, f in stages]
    assert fractions == sorted(fractions) and fractions[-1] == 1.0


def test_process_rejects_videos_over_the_limit(sample_video, transcript, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "transcribe_video", lambda *a, **k: transcript)
    with pytest.raises(ClipadorError, match="limite"):
        process(sample_video, tmp_path / "out", Options(max_minutes=0.5))


def test_process_missing_file(tmp_path):
    with pytest.raises(ClipadorError, match="Não encontrei"):
        process(tmp_path / "nao-existe.mp4", tmp_path / "out")
