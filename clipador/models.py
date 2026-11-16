"""Estruturas de dados compartilhadas."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class Transcript:
    language: str
    duration: float
    segments: list[Segment] = field(default_factory=list)

    def all_words(self) -> list[Word]:
        return [w for seg in self.segments for w in seg.words]

    def text_between(self, start: float, end: float) -> str:
        parts = [s.text.strip() for s in self.segments if s.end > start and s.start < end]
        return " ".join(p for p in parts if p)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Transcript":
        segments = []
        for seg in data.get("segments", []):
            words = [Word(**w) for w in seg.get("words", [])]
            segments.append(Segment(seg["start"], seg["end"], seg["text"], words))
        return cls(data.get("language", "?"), float(data["duration"]), segments)


@dataclass
class Highlight:
    """Um trecho escolhido do vídeo original."""

    start: float
    end: float
    score: float
    title: str = ""
    reason: str = ""
    source: str = "heuristica"  # "heuristica" ou "claude"

    @property
    def duration(self) -> float:
        return self.end - self.start
