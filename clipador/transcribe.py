"""Transcrição do áudio com timestamps por palavra (faster-whisper, roda no seu PC)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .models import Segment, Transcript, Word
from .utils import ClipadorError, run


def extract_audio(video: str | Path, wav_path: str | Path) -> Path:
    run([
        "ffmpeg", "-y", "-v", "error", "-i", video,
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav_path,
    ])
    return Path(wav_path)


def transcribe_video(
    video: str | Path,
    work_dir: str | Path,
    model_size: str = "small",
    language: str | None = None,
    duration: float = 0.0,
    on_progress: Callable[[float], None] | None = None,
) -> Transcript:
    """Transcreve o vídeo. O resultado é salvo em cache dentro de work_dir."""
    video = Path(video)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    cache = work / f"transcript_{model_size}_{language or 'auto'}.json"
    size = video.stat().st_size
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("_video_size") == size:
                return Transcript.from_dict(data)
        except (OSError, ValueError, KeyError, TypeError):
            pass  # cache quebrado: transcreve de novo

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise ClipadorError(
            "O faster-whisper não está instalado. Rode: pip install -r requirements.txt"
        ) from exc

    wav = extract_audio(video, work / "audio.wav")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments_iter, info = model.transcribe(
        str(wav),
        language=language,
        word_timestamps=True,
        vad_filter=True,
        beam_size=1,
    )
    total = info.duration or duration or 1.0

    segments: list[Segment] = []
    for seg in segments_iter:
        words = [
            Word(w.word.strip(), float(w.start), float(w.end))
            for w in (seg.words or [])
            if w.word.strip()
        ]
        segments.append(Segment(float(seg.start), float(seg.end), seg.text.strip(), words))
        if on_progress:
            on_progress(min(1.0, seg.end / total))

    transcript = Transcript(info.language or (language or "?"), float(duration or total), segments)
    payload = transcript.to_dict()
    payload["_video_size"] = size
    cache.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    wav.unlink(missing_ok=True)
    return transcript
