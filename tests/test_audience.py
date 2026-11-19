import json
from pathlib import Path

import numpy as np
import pytest

from clipador import audience as aud
from clipador import pipeline
from clipador.highlights import find_highlights
from clipador.models import Segment, Transcript, Word
from clipador.pipeline import Options, process
from clipador.utils import ClipadorError


def flat_transcript(duration: float = 60.0) -> Transcript:
    """Todas as frases iguais e sem nada de especial: só a audiência pode destacar um trecho."""
    segments = []
    for i in range(int(duration // 5)):
        start, end = i * 5.0, i * 5.0 + 4.8
        text = "Então a gente conversa um pouco sobre o assunto de hoje."
        tokens = text.split()
        step = (end - start) / len(tokens)
        words = [Word(t, start + k * step, start + (k + 1) * step) for k, t in enumerate(tokens)]
        segments.append(Segment(start, end, text, words))
    return Transcript("pt", duration, segments)


def spike_timestamps(start: float, end: float, n: int = 200) -> list[float]:
    return list(np.linspace(start, end, n))


# --------------------------------------------------------------------------- sinal

def test_chat_density_is_shifted_earlier_to_compensate_reaction_delay():
    density = aud.chat_density_per_second([50.0] * 30, duration=60, smooth=1)
    assert int(np.argmax(density)) == 42  # 50 s - 8 s de atraso do chat


def test_chat_spike_wins_when_nothing_else_stands_out():
    chat = aud.chat_density_per_second(spike_timestamps(38, 48), duration=60)
    audience = aud.combine_audience(chat, None, 60)
    found = find_highlights(
        flat_transcript(), np.full(60, 0.05), num_clips=2, min_len=15, max_len=30,
        use_claude=False, audience=audience,
    )
    best = found[0]
    assert best.start <= 35 <= best.end
    assert "audiência" in best.reason.lower()


def test_without_audience_nothing_changes_for_flat_input():
    found = find_highlights(flat_transcript(), np.full(60, 0.05), num_clips=2, min_len=15, max_len=30, use_claude=False)
    assert found and all("audiência" not in h.reason.lower() for h in found)


def test_no_speech_video_uses_audience_too():
    empty = Transcript("?", 120.0, [])
    chat = aud.chat_density_per_second(spike_timestamps(88, 100, 300), duration=120)
    found = find_highlights(
        empty, np.full(120, 0.02), num_clips=2, min_len=20, max_len=40,
        use_claude=False, audience=aud.combine_audience(chat, None, 120),
    )
    assert found[0].source == "audio"
    assert found[0].start <= 85 <= found[0].end
    assert "audiência" in found[0].reason.lower()


def test_flat_signals_are_ignored_and_peaks_are_found():
    assert aud.combine_audience(np.zeros(60), np.full(60, 0.3), 60) is None
    chat = aud.chat_density_per_second(spike_timestamps(38, 48), duration=60)
    peaks = aud.top_peaks(aud.combine_audience(chat, None, 60))
    assert peaks and 28 <= peaks[0] <= 42


def test_heatmap_to_per_second():
    out = aud.heatmap_per_second(
        [{"start_time": 0, "end_time": 10, "value": 0.2}, {"start_time": 10, "end_time": 20, "value": 1.0}], 30
    )
    assert out[5] == 0.2 and out[15] == 1.0 and out[25] == 0.0 and len(out) == 30


# --------------------------------------------------------------------------- formatos de arquivo

def _live_chat_line(ms: int) -> str:
    return json.dumps({"replayChatItemAction": {"actions": [{"addChatItemAction": {"item": {}}}], "videoOffsetTimeMsec": str(ms)}})


def test_parse_youtube_live_chat_jsonl(tmp_path):
    lines = [_live_chat_line(1000 * s) for s in range(10, 40)]
    lines.append(json.dumps({"replayChatItemAction": {"actions": [{"removeChatItemAction": {}}], "videoOffsetTimeMsec": "5000"}}))
    lines.append("isso nao e json {")
    f = tmp_path / "abc.live_chat.json"
    f.write_text("\n".join(lines), encoding="utf-8")
    stamps = aud.parse_chat_timestamps(f)
    assert len(stamps) == 30 and stamps[0] == 10.0


def test_parse_twitch_downloader_json(tmp_path):
    f = tmp_path / "chat.json"
    f.write_text(json.dumps({"comments": [{"content_offset_seconds": 12.5}, {"content_offset_seconds": 40}]}), encoding="utf-8")
    assert aud.parse_chat_timestamps(f) == [12.5, 40.0]


def test_parse_plain_text_and_csv(tmp_path):
    f = tmp_path / "chat.txt"
    f.write_text("12.5\n13,5,olha isso\n\n  20,mensagem\nabc\n", encoding="utf-8")
    assert aud.parse_chat_timestamps(f) == [12.5, 13.5, 20.0]


# --------------------------------------------------------------------------- busca automática

def test_fetch_signals_never_raises(tmp_path, monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("sem internet")

    monkeypatch.setattr("yt_dlp.YoutubeDL", Boom)
    assert aud.fetch_signals("https://youtu.be/x", tmp_path, 60) == (None, None)


def test_fetch_signals_reads_chat_and_heatmap(tmp_path, monkeypatch):
    class Fake:
        def __init__(self, options):
            self.out = Path(options["outtmpl"]).parent

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=True):
            (self.out / "abc.live_chat.json").write_text(
                "\n".join(_live_chat_line(1000 * s) for s in range(30, 60)), encoding="utf-8"
            )
            return {"id": "abc", "heatmap": [{"start_time": 0, "end_time": 30, "value": 0.5}]}

    monkeypatch.setattr("yt_dlp.YoutubeDL", Fake)
    chat, replay = aud.fetch_signals("https://youtu.be/abc", tmp_path, 60)
    assert chat is not None and len(chat) == 60
    assert replay is not None and replay[10] == 0.5


# --------------------------------------------------------------------------- pipeline

def test_pipeline_uses_chat_file(sample_video, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "transcribe_video", lambda *a, **k: flat_transcript())
    chat = tmp_path / "chat.txt"
    chat.write_text("\n".join(f"{t:.2f}" for t in spike_timestamps(38, 48)), encoding="utf-8")
    _, clips = process(
        sample_video, tmp_path / "out",
        Options(num_clips=2, min_len=15, max_len=30, use_claude=False, chat_file=str(chat)),
    )
    assert clips and clips[0].start <= 35 <= clips[0].end
    assert "audiência" in clips[0].reason.lower()


def test_pipeline_rejects_missing_or_tiny_chat_file(sample_video, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "transcribe_video", lambda *a, **k: flat_transcript())
    with pytest.raises(ClipadorError, match="Não encontrei o arquivo de chat"):
        process(sample_video, tmp_path / "o1", Options(chat_file=str(tmp_path / "nao-existe.txt")))
    tiny = tmp_path / "tiny.txt"
    tiny.write_text("1\n2\n3\n", encoding="utf-8")
    with pytest.raises(ClipadorError, match="só 3 mensagens"):
        process(sample_video, tmp_path / "o2", Options(chat_file=str(tiny)))
