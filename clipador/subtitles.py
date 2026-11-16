"""Legendas palavra por palavra (formato ASS) pra queimar no vídeo vertical."""

from __future__ import annotations

from pathlib import Path

from .models import Transcript, Word

PUNCT_BREAK = (".", "!", "?", ",", ";", ":", "…")


def words_for_clip(transcript: Transcript, start: float, end: float) -> list[Word]:
    """Palavras que caem dentro do clipe, com tempos relativos ao início dele."""
    out: list[Word] = []
    for seg in transcript.segments:
        if seg.end <= start or seg.start >= end:
            continue
        if seg.words:
            words = seg.words
        else:  # transcrição sem tempo por palavra: reparte o segmento por igual
            tokens = seg.text.split()
            if not tokens:
                continue
            step = (seg.end - seg.start) / len(tokens)
            words = [
                Word(t, seg.start + i * step, seg.start + (i + 1) * step)
                for i, t in enumerate(tokens)
            ]
        for w in words:
            if w.end > start and w.start < end:
                out.append(Word(w.text, max(w.start, start) - start, min(w.end, end) - start))
    return out


def group_words(words: list[Word], max_words: int = 3, max_chars: int = 20, max_gap: float = 0.8) -> list[list[Word]]:
    groups: list[list[Word]] = []
    current: list[Word] = []
    for w in words:
        if current:
            too_long = len(current) >= max_words or sum(len(x.text) + 1 for x in current) + len(w.text) > max_chars
            gap = w.start - current[-1].end > max_gap
            if too_long or gap:
                groups.append(current)
                current = []
        current.append(w)
        if w.text.endswith(PUNCT_BREAK):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _ts(seconds: float) -> str:
    cs = int(round(max(0.0, seconds) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _clean(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},&H0000D4FF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,2,2,70,70,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_ass(
    words: list[Word],
    path: str | Path,
    width: int = 1080,
    height: int = 1920,
    font: str = "Arial",
    font_size: int = 86,
    margin_v: int = 430,
) -> Path | None:
    """Gera o arquivo .ass. Devolve None se não há palavras (clipe sem fala)."""
    if not words:
        return None
    groups = group_words(words)
    lines = [HEADER.format(w=width, h=height, font=font, size=font_size, margin_v=margin_v)]
    for idx, group in enumerate(groups):
        start = group[0].start
        end = group[-1].end
        if idx + 1 < len(groups):  # segura a legenda até perto da próxima, sem piscar
            end = min(groups[idx + 1][0].start, end + 0.25)
        end = max(end, start + 0.15)

        parts = []
        for k, w in enumerate(group):
            nxt = group[k + 1].start if k + 1 < len(group) else w.end
            cs = max(5, int(round((nxt - w.start) * 100)))
            parts.append(f"{{\\kf{cs}}}{_clean(w.text)}")
        text = " ".join(parts)
        lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Default,,0,0,0,,{text}")

    path = Path(path)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
