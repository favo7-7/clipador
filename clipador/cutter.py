"""Corta o trecho, deixa em 9:16 (1080x1920) e queima a legenda."""

from __future__ import annotations

from pathlib import Path

from .utils import run

WIDTH, HEIGHT = 1080, 1920

MODES = {
    "fill": "Preenche a tela cortando as laterais",
    "blur": "Vídeo inteiro no meio, com fundo desfocado",
}


def _filters(mode: str, ass_name: str | None) -> list[str]:
    sub = f",subtitles={ass_name}" if ass_name else ""
    if mode == "blur":
        graph = (
            f"[0:v]split=2[a][b];"
            f"[a]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},boxblur=25:3[bg];"
            f"[b]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p{sub}[v]"
        )
        return ["-filter_complex", graph, "-map", "[v]", "-map", "0:a?"]
    graph = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},format=yuv420p{sub}"
    )
    return ["-vf", graph, "-map", "0:v:0", "-map", "0:a?"]


def cut_clip(
    video: str | Path,
    out_path: str | Path,
    start: float,
    end: float,
    ass_path: str | Path | None = None,
    mode: str = "fill",
) -> Path:
    """Gera um clipe vertical. Os tempos da legenda são relativos ao início do clipe."""
    if mode not in MODES:
        raise ValueError(f"mode deve ser um de {list(MODES)}")
    video = Path(video).resolve()
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cwd = None
    ass_name = None
    if ass_path:
        ass = Path(ass_path).resolve()
        cwd, ass_name = ass.parent, ass.name  # caminho relativo evita dor de cabeça com "C:\" no filtro

    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{start:.3f}", "-t", f"{max(0.5, end - start):.3f}",
        "-i", video,
        *_filters(mode, ass_name),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-movflags", "+faststart",
        out_path,
    ]
    run(cmd, cwd=cwd)
    return out_path
