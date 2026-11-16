"""Funções pequenas usadas pelo resto do projeto."""

from __future__ import annotations

import re
import shutil
import subprocess
import unicodedata
from pathlib import Path


class ClipadorError(Exception):
    """Erro com mensagem amigável, pensada pra ser mostrada ao usuário."""


def require_ffmpeg() -> None:
    """Garante que o FFmpeg está instalado e acessível no PATH."""
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise ClipadorError(
                f"Não encontrei o '{tool}'. Instale o FFmpeg e abra um terminal novo "
                "(o passo a passo está no README)."
            )


def run(cmd: list, cwd: str | Path | None = None) -> subprocess.CompletedProcess:
    """Roda um comando e levanta ClipadorError com o final do log se falhar."""
    proc = subprocess.run(
        [str(c) for c in cmd],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd) if cwd else None,
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise ClipadorError(f"Falha ao rodar {cmd[0]}:\n{tail}")
    return proc


def probe_duration(path: str | Path) -> float:
    """Duração do arquivo de mídia em segundos."""
    out = run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ]
    ).stdout.strip()
    try:
        return float(out)
    except ValueError as exc:
        raise ClipadorError(f"Não consegui ler a duração de {path}.") from exc


def slugify(text: str, max_len: int = 40) -> str:
    """'Meu Vídeo Incrível!' -> 'meu-video-incrivel' (seguro pra nome de arquivo)."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].strip("-") or "clip"


def fmt_time(seconds: float) -> str:
    """75 -> '01:15'  |  3700 -> '1:01:40'."""
    total = max(0, int(round(seconds)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
