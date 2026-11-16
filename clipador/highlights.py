"""Escolha dos melhores trechos do vídeo.

Três estratégias, da mais rica pra mais simples:

1. Claude (opcional): se existir ANTHROPIC_API_KEY, uma IA lê a transcrição e escolhe.
2. Heurística: combina volume do áudio, ritmo da fala, exclamações/perguntas,
   palavras de impacto e um "gancho" no começo. Roda 100% local.
3. Só áudio: pra vídeos sem fala (gameplay, trailer), usa os picos de volume.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re

import numpy as np

from .models import Highlight, Segment, Transcript
from .utils import fmt_time

log = logging.getLogger(__name__)

PAD_BEFORE = 0.2
PAD_AFTER = 0.4
MIN_GAP = 2.0  # segundos mínimos entre dois clipes escolhidos

POWER_WORDS = {
    # português
    "incrível", "inacreditável", "absurdo", "absurda", "nunca", "jamais", "segredo", "verdade",
    "mentira", "erro", "cuidado", "atenção", "loucura", "louco", "chocante", "maior", "melhor",
    "pior", "impossível", "ninguém", "todo", "dinheiro", "milhão", "milhões", "bilhão", "bilhões",
    "urgente", "perigo", "surreal", "histórico", "primeira", "primeiro", "acabou", "olha",
    # inglês
    "insane", "crazy", "never", "secret", "truth", "shocking", "biggest", "best", "worst",
    "impossible", "nobody", "everyone", "million", "billion", "wow", "omg", "unbelievable",
    "mistake", "warning", "huge", "history", "first", "look",
}


# --------------------------------------------------------------------------- utilidades

def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w']+", text.lower())


def _short_title(text: str, limit: int = 64) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    first = re.split(r"(?<=[.!?…])\s+", text, maxsplit=1)[0]
    if len(first) < 12 and len(text) > len(first):
        first = text
    if len(first) <= limit:
        return first.rstrip(" ,;:")
    return first[:limit].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


def _normalize_loudness(loudness: np.ndarray, duration: float) -> np.ndarray:
    loud = np.asarray(loudness, dtype=float)
    if loud.size == 0:
        return np.zeros(max(1, int(math.ceil(duration))))
    std = float(loud.std()) or 1e-6
    return np.clip((loud - float(np.median(loud))) / std, -2.0, 4.0)


def _normalize_scores(raws: list[float]) -> list[float]:
    """Nota relativa ao próprio vídeo, de 10 a 100 (o melhor trecho vale 100).

    O piso em 10 evita mostrar "nota 0" pra um trecho que foi escolhido, o que confundiria.
    """
    if not raws:
        return []
    lo, hi = min(raws), max(raws)
    if hi - lo < 1e-9:
        return [100.0] * len(raws)
    return [round(10.0 + 90.0 * (r - lo) / (hi - lo), 1) for r in raws]


def _overlaps(a_start: float, a_end: float, b_start: float, b_end: float, gap: float = MIN_GAP) -> bool:
    return not (a_end + gap <= b_start or a_start >= b_end + gap)


def _pick(candidates: list[tuple], num_clips: int) -> list[tuple]:
    """candidates: (start, end, raw, ...). Pega os melhores sem sobreposição."""
    chosen: list[tuple] = []
    for cand in sorted(candidates, key=lambda c: c[2], reverse=True):
        if all(not _overlaps(cand[0], cand[1], c[0], c[1]) for c in chosen):
            chosen.append(cand)
        if len(chosen) >= num_clips:
            break
    return chosen


def _window_slice(z: np.ndarray, start: float, end: float) -> np.ndarray:
    a = max(0, int(start))
    b = max(a + 1, int(math.ceil(end)))
    chunk = z[a:b]
    return chunk if chunk.size else np.zeros(1)


# --------------------------------------------------------------------------- heurística

def _score_window(segs: list[Segment], start: float, end: float, z: np.ndarray, med_rate: float):
    chunk = _window_slice(z, start, end)
    loud_mean = float(chunk.mean())
    loud_peak = float(np.percentile(chunk, 90))

    text = " ".join(s.text.strip() for s in segs)
    words = _tokens(text)
    n = max(len(words), 1)
    speech_time = max(sum(s.end - s.start for s in segs), 1e-6)
    coverage = min(1.0, speech_time / max(end - start, 1e-6))
    rate_z = (n / speech_time) / med_rate - 1.0

    emphasis = text.count("!") + text.count("?")
    power = sum(1 for w in words if w in POWER_WORDS)
    numbers = len(re.findall(r"\d+", text))
    text_score = (emphasis * 1.0 + power * 1.5 + numbers * 0.5) / math.sqrt(n)

    opening = segs[0].text.strip()
    hook = 1.0 if ("?" in opening or any(w in POWER_WORDS for w in _tokens(opening)[:12])) else 0.0

    raw = loud_mean + 0.6 * loud_peak + 0.8 * rate_z + 2.0 * text_score + 0.8 * hook + 1.5 * coverage

    reasons = []
    if loud_mean > 0.5 or loud_peak > 1.5:
        reasons.append("áudio mais forte que o resto do vídeo")
    if rate_z > 0.15:
        reasons.append("fala mais acelerada")
    if emphasis >= 2:
        reasons.append("exclamações e perguntas")
    if power >= 2:
        reasons.append("palavras de impacto")
    if hook:
        reasons.append("começa com um gancho")
    reason = "; ".join(reasons) or "boa densidade de fala"
    return raw, reason[0].upper() + reason[1:]


def heuristic_highlights(
    transcript: Transcript,
    loudness: np.ndarray,
    num_clips: int = 5,
    min_len: float = 20.0,
    max_len: float = 55.0,
) -> list[Highlight]:
    segs = [s for s in transcript.segments if s.text.strip()]
    if not segs:
        return []
    duration = transcript.duration
    z = _normalize_loudness(loudness, duration)
    rates = [len(_tokens(s.text)) / max(s.end - s.start, 0.5) for s in segs]
    med_rate = float(np.median(rates)) or 1.0

    candidates: list[tuple] = []
    for i, first in enumerate(segs):
        for j in range(i, len(segs)):
            start, end = first.start, segs[j].end
            length = end - start
            if length > max_len:
                break
            if length < min_len:
                continue
            raw, reason = _score_window(segs[i : j + 1], start, end, z, med_rate)
            candidates.append((start, end, raw, reason, segs[i : j + 1]))

    if not candidates:
        # vídeo curto (ou frases muito longas): usa o trecho que couber
        start = segs[0].start
        end = min(segs[-1].end, start + max_len)
        inside = [s for s in segs if s.start < end]
        raw, reason = _score_window(inside, start, end, z, med_rate)
        candidates = [(start, end, raw, reason, inside)]

    chosen = _pick(candidates, num_clips)
    scores = _normalize_scores([c[2] for c in candidates])
    score_of = {(c[0], c[1]): s for c, s in zip(candidates, scores)}

    out = []
    for start, end, raw, reason, window in chosen:
        out.append(
            Highlight(
                start=max(0.0, start - PAD_BEFORE),
                end=min(duration, end + PAD_AFTER),
                score=score_of[(start, end)],
                title=_short_title(" ".join(s.text for s in window)),
                reason=reason,
                source="heuristica",
            )
        )
    return sorted(out, key=lambda h: h.score, reverse=True)


# --------------------------------------------------------------------------- só áudio

def loudness_highlights(
    loudness: np.ndarray,
    duration: float,
    num_clips: int = 5,
    min_len: float = 20.0,
    max_len: float = 55.0,
) -> list[Highlight]:
    """Pra vídeos sem fala: escolhe as janelas com mais energia sonora."""
    if duration <= max_len:
        return [Highlight(0.0, duration, 100.0, "Vídeo inteiro", "Vídeo curto, usado por completo", "audio")]

    z = _normalize_loudness(loudness, duration)
    target = (min_len + max_len) / 2
    candidates: list[tuple] = []
    t = 0.0
    while t + min_len <= duration:
        end = min(duration, t + target)
        chunk = _window_slice(z, t, end)
        raw = float(chunk.mean() + 0.6 * np.percentile(chunk, 90) + 0.3 * chunk.std())
        candidates.append((t, end, raw))
        t += 5.0

    chosen = _pick(candidates, num_clips)
    scores = _normalize_scores([c[2] for c in candidates])
    score_of = {(c[0], c[1]): s for c, s in zip(candidates, scores)}
    out = [
        Highlight(
            start=s,
            end=e,
            score=score_of[(s, e)],
            title=f"Momento em {fmt_time(s)}",
            reason="Pico de volume e movimento sonoro (sem fala detectada)",
            source="audio",
        )
        for s, e, _ in chosen
    ]
    return sorted(out, key=lambda h: h.score, reverse=True)


# --------------------------------------------------------------------------- Claude (opcional)

def _snap(segments: list[Segment], start: float, end: float) -> tuple[float, float]:
    s = min(segments, key=lambda x: abs(x.start - start)).start
    e = min(segments, key=lambda x: abs(x.end - end)).end
    return s, e


def claude_highlights(
    transcript: Transcript,
    num_clips: int,
    min_len: float,
    max_len: float,
) -> list[Highlight]:
    import anthropic

    segments = [s for s in transcript.segments if s.text.strip()]
    lines = "\n".join(f"[{s.start:.1f}-{s.end:.1f}] {s.text.strip()}" for s in segments)[:60000]
    prompt = (
        f"Abaixo está a transcrição com tempos (em segundos) de um vídeo. Escolha até {num_clips} "
        f"trechos para virar vídeos curtos de TikTok.\n\n"
        f"Regras:\n"
        f"- Cada trecho dura entre {min_len:.0f} e {max_len:.0f} segundos.\n"
        f"- Comece e termine nos limites dos tempos da transcrição, sem cortar frases.\n"
        f"- O trecho precisa fazer sentido sozinho e ter um gancho forte nos primeiros 3 segundos.\n"
        f"- Prefira momentos de surpresa, emoção, humor, revelação ou opinião forte.\n"
        f"- Os trechos não podem se sobrepor.\n\n"
        f"Responda SOMENTE com um array JSON, sem texto antes ou depois, neste formato:\n"
        f'[{{"start": 12.3, "end": 48.0, "title": "título curto no idioma do vídeo", '
        f'"reason": "uma frase em português dizendo por que esse trecho funciona", "score": 0-100}}]\n\n'
        f"Transcrição:\n{lines}"
    )
    client = anthropic.Anthropic()
    message = client.messages.create(
        model=os.environ.get("CLIPADOR_CLAUDE_MODEL", "claude-sonnet-5-5"),
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(getattr(block, "text", "") for block in message.content)
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise ValueError("resposta sem JSON")
    data = json.loads(match.group(0))

    out: list[Highlight] = []
    for item in data:
        try:
            start, end = _snap(segments, float(item["start"]), float(item["end"]))
        except (KeyError, TypeError, ValueError):
            continue
        length = end - start
        if length < min_len * 0.5 or length > max_len * 1.25:
            continue
        if any(_overlaps(start, end, h.start, h.end, gap=0.0) for h in out):
            continue
        out.append(
            Highlight(
                start=max(0.0, start - PAD_BEFORE),
                end=min(transcript.duration, end + PAD_AFTER),
                score=float(item.get("score", 80)),
                title=str(item.get("title") or _short_title(transcript.text_between(start, end)))[:80],
                reason=str(item.get("reason", "Escolhido pela IA")),
                source="claude",
            )
        )
    return sorted(out, key=lambda h: h.score, reverse=True)[:num_clips]


# --------------------------------------------------------------------------- entrada principal

def find_highlights(
    transcript: Transcript,
    loudness: np.ndarray,
    num_clips: int = 5,
    min_len: float = 20.0,
    max_len: float = 55.0,
    use_claude: bool = True,
) -> list[Highlight]:
    has_speech = any(s.text.strip() for s in transcript.segments)

    if has_speech and use_claude and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            found = claude_highlights(transcript, num_clips, min_len, max_len)
            if found:
                return found
        except Exception as exc:  # noqa: BLE001 - qualquer falha cai pra heurística
            log.warning("Seleção com Claude falhou (%s); usando heurística.", exc)

    if has_speech:
        found = heuristic_highlights(transcript, loudness, num_clips, min_len, max_len)
        if found:
            return found

    return loudness_highlights(loudness, transcript.duration, num_clips, min_len, max_len)
