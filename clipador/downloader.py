"""Baixa o vídeo a partir de um link (YouTube e outros sites suportados pelo yt-dlp)."""

from __future__ import annotations

import ipaddress
import re
import socket
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from .utils import ClipadorError


def is_url(text: str) -> bool:
    return bool(re.match(r"^https?://", text.strip(), re.IGNORECASE))


def validate_public_url(url: str) -> None:
    """Recusa endereços internos (localhost, rede privada, metadados de nuvem).

    Importante num servidor público: sem isso, alguém poderia pedir pro servidor
    baixar "http://localhost/..." e enxergar coisas que não deveria. Não cobre
    redirecionamentos feitos pelo site de destino, mas barra o caso direto.
    """
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ClipadorError("Esse link não parece válido. Use um endereço que comece com http:// ou https://.")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ClipadorError("Não consegui encontrar esse endereço. Confira o link.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified
        ):
            raise ClipadorError("Esse endereço não é permitido. Use um link público de vídeo.")


def download_video(
    url: str,
    dest_dir: str | Path,
    on_progress: Callable[[float], None] | None = None,
    max_seconds: float | None = None,
) -> tuple[Path, str]:
    """Baixa o vídeo (até 1080p) e devolve (caminho_do_arquivo, título).

    Se max_seconds for dado, confere a duração ANTES de baixar.
    """
    try:
        import yt_dlp
        from yt_dlp.utils import DownloadError
    except ImportError as exc:
        raise ClipadorError("O yt-dlp não está instalado. Rode: pip install -r requirements.txt") from exc

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    def hook(data: dict) -> None:
        if on_progress and data.get("status") == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            if total:
                on_progress(min(1.0, data.get("downloaded_bytes", 0) / total))

    options = {
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(dest / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            if max_seconds:
                meta = ydl.extract_info(url, download=False)
                duration = meta.get("duration")
                if duration and duration > max_seconds:
                    raise ClipadorError(
                        f"Esse vídeo tem {int(duration // 60)} min e o limite aqui é "
                        f"{int(max_seconds // 60)} min. Tente um vídeo mais curto."
                    )
            info = ydl.extract_info(url, download=True)
            downloads = info.get("requested_downloads") or []
            path = Path(downloads[0]["filepath"]) if downloads else Path(ydl.prepare_filename(info))
    except DownloadError as exc:
        raise ClipadorError(
            "Não consegui baixar esse vídeo. Alguns sites bloqueiam downloads feitos por "
            "servidores; nesse caso, baixe o vídeo e envie o arquivo. "
            "(Se estiver rodando no seu PC, tente: pip install -U yt-dlp)"
        ) from exc

    if not path.exists() and path.with_suffix(".mp4").exists():
        path = path.with_suffix(".mp4")
    if not path.exists():
        raise ClipadorError("O download terminou, mas não encontrei o arquivo de vídeo.")

    return path, str(info.get("title") or info.get("id") or path.stem)
