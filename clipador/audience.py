"""Sinais da audiência: onde o chat explode e onde as pessoas mais reveem o vídeo.

Quando muita gente comenta ao mesmo tempo, normalmente aconteceu algo importante. Esse módulo
transforma isso em um número por segundo, que a escolha dos trechos soma aos outros sinais
(volume, ritmo da fala, palavras de impacto).

Fontes aceitas:
- chat de replay de live do YouTube (baixado pelo yt-dlp, arquivo *.live_chat.json);
- chat exportado do Twitch (JSON do TwitchDownloader);
- um .txt/.csv simples com um tempo em segundos por linha ("123.4" ou "123.4,mensagem");
- o gráfico "mais revisto" do YouTube (heatmap), quando o vídeo tem.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

CHAT_LAG = 8.0        # o chat reage alguns segundos DEPOIS do acontecimento; voltamos esse tempo
MIN_MESSAGES = 20     # com menos mensagens que isso o sinal é só ruído


# --------------------------------------------------------------------------- leitura do chat

def _live_chat_offset_ms(obj: dict) -> float | None:
    """Uma linha do .live_chat.json do yt-dlp -> tempo da mensagem em ms (ou None)."""
    action = obj.get("replayChatItemAction")
    if not isinstance(action, dict):
        return None
    if not any("addChatItemAction" in a for a in action.get("actions", []) if isinstance(a, dict)):
        return None
    try:
        return float(action["videoOffsetTimeMsec"])
    except (KeyError, TypeError, ValueError):
        return None


def parse_chat_timestamps(path: str | Path) -> list[float]:
    """Lê um arquivo de chat e devolve o tempo (em segundos) de cada mensagem."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")

    if text.lstrip().startswith("{"):  # JSON único (TwitchDownloader)
        try:
            data = json.loads(text)
            if isinstance(data, dict) and isinstance(data.get("comments"), list):
                return [
                    float(c["content_offset_seconds"])
                    for c in data["comments"]
                    if isinstance(c, dict) and "content_offset_seconds" in c
                ]
        except ValueError:
            pass  # não é um JSON só: provavelmente JSON Lines (yt-dlp), tratado abaixo

    stamps: list[float] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("{"):  # JSON Lines do yt-dlp
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            ms = _live_chat_offset_ms(obj) if isinstance(obj, dict) else None
            if ms is not None:
                stamps.append(ms / 1000.0)
            continue
        match = re.match(r"^\s*(\d+(?:[.,]\d+)?)", line)  # "123.4" ou "123,4,mensagem"
        if match:
            stamps.append(float(match.group(1).replace(",", ".")))
    return stamps


# --------------------------------------------------------------------------- sinais por segundo

def chat_density_per_second(
    timestamps: list[float], duration: float, lag: float = CHAT_LAG, smooth: int = 5
) -> np.ndarray:
    """Quantas mensagens por segundo, suavizado, já deslocado pelo atraso natural do chat."""
    total = max(1, int(np.ceil(duration)))
    counts = np.zeros(total)
    for t in timestamps:
        if t < 0 or t >= total:
            continue
        counts[max(0, int(t - lag))] += 1.0
    if smooth > 1:
        counts = np.convolve(counts, np.ones(smooth) / smooth, mode="same")
    return counts


def heatmap_per_second(heatmap: list[dict] | None, duration: float) -> np.ndarray:
    """Gráfico 'mais revisto' do YouTube (lista de {start_time, end_time, value}) -> por segundo."""
    total = max(1, int(np.ceil(duration)))
    out = np.zeros(total)
    for seg in heatmap or []:
        try:
            a = max(0, int(seg.get("start_time", 0)))
            b = min(total, int(np.ceil(seg.get("end_time", a + 1))))
            out[a:b] = float(seg.get("value", 0.0))
        except (TypeError, ValueError):
            continue
    return out


def _zscore(arr: np.ndarray) -> np.ndarray | None:
    arr = np.asarray(arr, dtype=float)
    std = float(arr.std())
    if arr.size == 0 or std < 1e-9:
        return None  # sinal "reto": não ajuda a distinguir nada
    return np.clip((arr - float(np.median(arr))) / std, -1.0, 4.0)


def combine_audience(
    chat: np.ndarray | None, replay: np.ndarray | None, duration: float
) -> np.ndarray | None:
    """Junta os sinais disponíveis em um só (média dos z-scores). None se não há nenhum útil."""
    parts = [z for z in (_zscore(a) for a in (chat, replay) if a is not None) if z is not None]
    if not parts:
        return None
    total = max(1, int(np.ceil(duration)))
    stacked = np.zeros((len(parts), total))
    for i, p in enumerate(parts):
        stacked[i, : min(total, len(p))] = p[:total]
    return stacked.mean(axis=0)


def top_peaks(signal: np.ndarray | None, count: int = 8, min_separation: int = 20) -> list[int]:
    """Segundos de maior reação, sem repetir picos colados um no outro."""
    if signal is None or len(signal) == 0:
        return []
    order = np.argsort(signal)[::-1]
    peaks: list[int] = []
    for idx in order:
        if signal[idx] <= 0.5:
            break
        if all(abs(int(idx) - p) >= min_separation for p in peaks):
            peaks.append(int(idx))
        if len(peaks) >= count:
            break
    return sorted(peaks)


# --------------------------------------------------------------------------- busca automática (YouTube)

def fetch_signals(
    url: str, work_dir: str | Path, duration: float
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Tenta pegar o chat de replay e o gráfico 'mais revisto' de um link do YouTube.

    Nunca derruba o processamento: se não existir (ou falhar), devolve None no lugar.
    """
    try:
        import yt_dlp
    except ImportError:
        return None, None

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    options = {
        "skip_download": True,
        "writesubtitles": True,
        "subtitleslangs": ["live_chat"],
        "outtmpl": str(work / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    chat = replay = None
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
        if info.get("heatmap"):
            replay = heatmap_per_second(info["heatmap"], duration)
        for chat_file in work.glob(f"{info.get('id', '')}*.live_chat.json"):
            stamps = parse_chat_timestamps(chat_file)
            if len(stamps) >= MIN_MESSAGES:
                chat = chat_density_per_second(stamps, duration)
            break
    except Exception as exc:  # noqa: BLE001 - sinal é opcional
        log.warning("Não consegui buscar chat/reproduções (%s). Seguindo sem eles.", exc)
    return chat, replay
