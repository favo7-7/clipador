"""Mede o volume do áudio segundo a segundo (um dos sinais de 'momento forte')."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

SAMPLE_RATE = 8000


def loudness_per_second(video: str | Path, duration: float) -> np.ndarray:
    """Devolve o RMS do áudio de cada segundo do vídeo (zeros se não houver áudio)."""
    total = max(1, int(np.ceil(duration)))
    cmd = [
        "ffmpeg", "-v", "error", "-i", str(video),
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    values: list[float] = []
    chunk_bytes = SAMPLE_RATE * 2 * 60  # lê 60 s por vez pra não estourar a memória
    try:
        while True:
            buf = proc.stdout.read(chunk_bytes)
            if not buf:
                break
            samples = np.frombuffer(buf[: len(buf) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0
            full = len(samples) // SAMPLE_RATE
            if full:
                frames = samples[: full * SAMPLE_RATE].reshape(full, SAMPLE_RATE)
                values.extend(np.sqrt((frames ** 2).mean(axis=1)).tolist())
            rest = samples[full * SAMPLE_RATE:]
            if len(rest):
                values.append(float(np.sqrt((rest ** 2).mean())))
    finally:
        proc.stdout.close()
        proc.wait()

    out = np.zeros(total)
    if values:
        k = min(total, len(values))
        out[:k] = np.asarray(values[:k])
    return out
