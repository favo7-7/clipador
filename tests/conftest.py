import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clipador.models import Segment, Transcript, Word  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg não instalado")


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory) -> Path:
    """60 s de vídeo horizontal 640x360 com áudio (um 'pico' de volume entre 30 s e 40 s)."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("FFmpeg não instalado")
    path = tmp_path_factory.mktemp("media") / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=60",
            "-f", "lavfi", "-i", "sine=frequency=300:duration=60",
            "-af", "volume='if(between(t,30,40),1.0,0.05)':eval=frame",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )
    return path


def make_transcript(duration: float = 60.0) -> Transcript:
    """Uma frase de 5 s por vez; a de 30-40 s é cheia de impacto."""
    segments = []
    for i in range(int(duration // 5)):
        start, end = i * 5.0, i * 5.0 + 4.8
        if 30 <= start < 40:
            text = "Isso é absurdo! Você nunca viu nada assim, olha só 100 mil!"
        else:
            text = "Então a gente conversa um pouco sobre o assunto de hoje."
        tokens = text.split()
        step = (end - start) / len(tokens)
        words = [Word(t, start + k * step, start + (k + 1) * step) for k, t in enumerate(tokens)]
        segments.append(Segment(start, end, text, words))
    return Transcript("pt", duration, segments)


@pytest.fixture
def transcript() -> Transcript:
    return make_transcript()
