"""Orquestra tudo: link/arquivo -> transcrição -> melhores trechos -> clipes verticais."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .audience import (
    MIN_MESSAGES,
    chat_density_per_second,
    combine_audience,
    fetch_signals,
    parse_chat_timestamps,
)
from .audio import loudness_per_second
from .cutter import cut_clip
from .downloader import download_video, is_url
from .highlights import find_highlights
from .subtitles import build_ass, words_for_clip
from .transcribe import transcribe_video
from .utils import ClipadorError, fmt_time, probe_duration, require_ffmpeg, slugify

# progress(etapa, fração_total_0_a_1, mensagem)
Progress = Callable[[str, float, str], None]


@dataclass
class Options:
    num_clips: int = 5
    min_len: float = 20.0
    max_len: float = 55.0
    mode: str = "fill"            # "fill" ou "blur"
    whisper_model: str = "base"   # tiny | base | small | medium
    language: str | None = None   # None = detectar sozinho
    captions: bool = True
    use_claude: bool = True
    max_minutes: float | None = None
    use_audience: bool = True     # tenta buscar chat/"mais revisto" quando a entrada é um link do YouTube
    chat_file: str | None = None  # arquivo de chat exportado (YouTube, Twitch ou .txt/.csv de tempos)


@dataclass
class ClipResult:
    file: str          # nome do arquivo dentro de <saida>/clips
    start: float
    end: float
    score: float
    title: str
    reason: str
    source: str

    @property
    def duration(self) -> float:
        return self.end - self.start


def process(
    source: str | Path,
    out_dir: str | Path,
    options: Options | None = None,
    progress: Progress | None = None,
) -> tuple[str, list[ClipResult]]:
    """Gera os clipes. Devolve (título_do_vídeo, lista_de_clipes)."""
    opts = options or Options()

    def report(stage: str, fraction: float, message: str = "") -> None:
        if progress:
            progress(stage, max(0.0, min(1.0, fraction)), message)

    require_ffmpeg()
    out = Path(out_dir)
    work = out / "work"
    clips_dir = out / "clips"
    work.mkdir(parents=True, exist_ok=True)
    clips_dir.mkdir(parents=True, exist_ok=True)

    # 1) vídeo de entrada ----------------------------------------------------------
    if is_url(str(source)):
        report("download", 0.0, "Baixando o vídeo…")
        video, title = download_video(
            str(source),
            work,
            on_progress=lambda f: report("download", 0.15 * f, "Baixando o vídeo…"),
            max_seconds=opts.max_minutes * 60 if opts.max_minutes else None,
        )
    else:
        video = Path(source)
        if not video.exists():
            raise ClipadorError(f"Não encontrei o arquivo: {video}")
        title = video.stem

    duration = probe_duration(video)
    if opts.max_minutes and duration > opts.max_minutes * 60:
        raise ClipadorError(
            f"O vídeo tem {fmt_time(duration)} e o limite aqui é {opts.max_minutes:.0f} min. "
            "Envie um vídeo mais curto."
        )

    # 2) transcrição ---------------------------------------------------------------
    report("transcribe", 0.15, "Transcrevendo a fala…")
    transcript = transcribe_video(
        video,
        work,
        model_size=opts.whisper_model,
        language=opts.language,
        duration=duration,
        on_progress=lambda f: report("transcribe", 0.15 + 0.5 * f, "Transcrevendo a fala…"),
    )

    # 3) melhores momentos ---------------------------------------------------------
    report("analyze", 0.65, "Procurando os melhores momentos…")
    loudness = loudness_per_second(video, duration)

    chat = replay = None
    if opts.chat_file:
        chat_path = Path(opts.chat_file)
        if not chat_path.exists():
            raise ClipadorError(f"Não encontrei o arquivo de chat: {chat_path}")
        stamps = parse_chat_timestamps(chat_path)
        if len(stamps) < MIN_MESSAGES:
            raise ClipadorError(
                f"O arquivo de chat tem só {len(stamps)} mensagens; preciso de pelo menos {MIN_MESSAGES}. "
                "Confira o formato (um tempo em segundos por linha, ou o chat exportado do YouTube/Twitch)."
            )
        chat = chat_density_per_second(stamps, duration)
    elif opts.use_audience and is_url(str(source)):
        report("analyze", 0.67, "Lendo o chat e os trechos mais revistos…")
        chat, replay = fetch_signals(str(source), work, duration)
    audience = combine_audience(chat, replay, duration)

    highlights = find_highlights(
        transcript,
        loudness,
        num_clips=opts.num_clips,
        min_len=opts.min_len,
        max_len=opts.max_len,
        use_claude=opts.use_claude,
        audience=audience,
    )
    if not highlights:
        raise ClipadorError("Não consegui achar trechos bons neste vídeo. Tente um vídeo mais longo.")

    # 4) cortes --------------------------------------------------------------------
    results: list[ClipResult] = []
    total = len(highlights)
    for i, h in enumerate(highlights, start=1):
        report("cut", 0.72 + 0.28 * (i - 1) / total, f"Cortando o clipe {i} de {total}…")
        name = f"{i:02d}-{slugify(h.title)}.mp4"
        ass = None
        if opts.captions:
            ass = build_ass(words_for_clip(transcript, h.start, h.end), work / f"clip{i:02d}.ass")
        cut_clip(video, clips_dir / name, h.start, h.end, ass, mode=opts.mode)
        results.append(ClipResult(name, h.start, h.end, h.score, h.title, h.reason, h.source))

    (out / "clips.json").write_text(
        json.dumps({"title": title, "clips": [asdict(r) for r in results]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report("done", 1.0, "Pronto")
    return title, results
