"""Servidor web (FastAPI): recebe um vídeo ou link, processa em segundo plano e serve os clipes.

Pensado pra ser público (portfólio), então tem limites: tamanho do arquivo, duração do vídeo,
tamanho da fila, e os arquivos são apagados depois de um tempo. Tudo ajustável por variáveis
de ambiente (veja _settings).
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..cutter import MODES
from ..downloader import is_url, validate_public_url
from ..pipeline import Options, process
from ..utils import ClipadorError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("clipador.web")

ALLOWED_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
ALLOWED_MODELS = {"tiny", "base", "small"}
ALLOWED_LANGS = {"", "pt", "en", "es"}
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+\.mp4$")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _settings() -> dict:
    return {
        "data_dir": Path(os.environ.get("CLIPADOR_DATA", "data")).resolve(),
        "max_upload_mb": _int_env("CLIPADOR_MAX_UPLOAD_MB", 300),
        "max_minutes": _int_env("CLIPADOR_MAX_MINUTES", 15),
        "ttl_seconds": _int_env("CLIPADOR_TTL_SECONDS", 3600),
        "max_queue": _int_env("CLIPADOR_MAX_QUEUE", 4),
        "allow_url": os.environ.get("CLIPADOR_ALLOW_URL", "1") != "0",
        "default_model": os.environ.get("CLIPADOR_MODEL", "base"),
    }


app = FastAPI(title="Clipador", docs_url=None, redoc_url=None)

_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=1)  # um vídeo por vez: transcrever é pesado


# --------------------------------------------------------------------------- jobs

def _update(job_id: str, **fields) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)


def _public(job: dict) -> dict:
    return {k: v for k, v in job.items() if not k.startswith("_")}


def _cleanup_old_jobs() -> None:
    cfg = _settings()
    cutoff = time.time() - cfg["ttl_seconds"]
    with _lock:
        stale = [jid for jid, j in _jobs.items() if j["created"] < cutoff and j["status"] in ("done", "error")]
        for jid in stale:
            del _jobs[jid]
    for jid in stale:
        shutil.rmtree(cfg["data_dir"] / jid, ignore_errors=True)
    # pastas órfãs (ex.: servidor reiniciado)
    if cfg["data_dir"].exists():
        for child in cfg["data_dir"].iterdir():
            try:
                if child.is_dir() and child.name not in _jobs and child.stat().st_mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True)
            except OSError:
                pass


def _run_job(job_id: str, source: str, options: Options, job_dir: Path, label: str | None = None) -> None:
    """label: nome a mostrar pro usuário (uploads guardam o nome original do arquivo)."""

    def progress(stage: str, fraction: float, message: str) -> None:
        _update(job_id, status="running", stage=stage, progress=round(fraction, 3), message=message)

    try:
        title, results = process(source, job_dir, options, progress)
        title = label or title
        clips = [
            {
                "url": f"/api/files/{job_id}/{r.file}",
                "file": r.file,
                "start": round(r.start, 2),
                "end": round(r.end, 2),
                "duration": round(r.duration, 1),
                "score": round(r.score),
                "title": r.title,
                "reason": r.reason,
                "source": r.source,
            }
            for r in results
        ]
        _update(job_id, status="done", stage="done", progress=1.0, message="Pronto", title=title, clips=clips)
    except ClipadorError as exc:
        log.warning("Job %s falhou: %s", job_id, exc)
        _update(job_id, status="error", error=str(exc), message="")
    except Exception as exc:  # noqa: BLE001
        log.exception("Falha inesperada no job %s", job_id)
        message = "Algo deu errado ao processar o vídeo. Tente outro arquivo ou um vídeo mais curto."
        if os.environ.get("CLIPADOR_DEBUG", "1") != "0":
            # Rodando no seu PC: mostra o erro técnico na própria página pra facilitar o diagnóstico.
            message += f" Detalhe técnico: {type(exc).__name__}: {str(exc)[:300]}"
        _update(job_id, status="error", error=message, message="")
    finally:
        # o original (upload ou download) e os temporários não precisam ficar no servidor
        shutil.rmtree(job_dir / "work", ignore_errors=True)
        shutil.rmtree(job_dir / "upload", ignore_errors=True)


# --------------------------------------------------------------------------- rotas

@app.get("/api/health")
def health() -> dict:
    cfg = _settings()
    return {
        "ok": True,
        "max_upload_mb": cfg["max_upload_mb"],
        "max_minutes": cfg["max_minutes"],
        "allow_url": cfg["allow_url"],
        "ai_picker": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


@app.post("/api/jobs", status_code=202)
def create_job(
    file: UploadFile | None = File(None),
    url: str = Form(""),
    num_clips: int = Form(5),
    min_len: float = Form(20),
    max_len: float = Form(45),
    mode: str = Form("fill"),
    language: str = Form(""),
    captions: bool = Form(True),
    model: str = Form(""),
) -> dict:
    cfg = _settings()
    url = url.strip()
    has_file = file is not None and bool(file.filename)

    if has_file == bool(url):
        raise HTTPException(400, "Envie um arquivo de vídeo ou cole um link (só um dos dois).")
    if url:
        if not cfg["allow_url"]:
            raise HTTPException(400, "Links estão desativados neste servidor. Envie o arquivo do vídeo.")
        if not is_url(url):
            raise HTTPException(400, "Esse link não parece válido. Ele precisa começar com http:// ou https://.")
        try:
            validate_public_url(url)
        except ClipadorError as exc:
            raise HTTPException(400, str(exc)) from exc

    if not 1 <= num_clips <= 8:
        raise HTTPException(400, "Escolha entre 1 e 8 clipes.")
    if not (10 <= min_len <= 60 and min_len < max_len <= 90):
        raise HTTPException(400, "Duração inválida: o mínimo vai de 10 a 60 s e o máximo precisa ser maior.")
    if mode not in MODES:
        raise HTTPException(400, "Enquadramento inválido.")
    if language not in ALLOWED_LANGS:
        raise HTTPException(400, "Idioma inválido.")
    model = model or cfg["default_model"]
    if model not in ALLOWED_MODELS:
        raise HTTPException(400, "Modelo de transcrição inválido.")

    _cleanup_old_jobs()
    with _lock:
        active = sum(1 for j in _jobs.values() if j["status"] in ("queued", "running"))
    if active >= cfg["max_queue"]:
        raise HTTPException(429, "A fila está cheia no momento. Tente de novo em alguns minutos.")

    job_id = uuid.uuid4().hex[:12]
    job_dir = cfg["data_dir"] / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    if has_file:
        suffix = Path(file.filename).suffix.lower()
        if suffix not in ALLOWED_EXT:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(400, "Formato não suportado. Use MP4, MOV, MKV, WebM ou AVI.")
        upload_dir = job_dir / "upload"
        upload_dir.mkdir()
        source_path = upload_dir / f"input{suffix}"
        limit = cfg["max_upload_mb"] * 1024 * 1024
        written = 0
        with open(source_path, "wb") as fh:
            while chunk := file.file.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    fh.close()
                    shutil.rmtree(job_dir, ignore_errors=True)
                    raise HTTPException(413, f"O arquivo passa de {cfg['max_upload_mb']} MB.")
                fh.write(chunk)
        source = str(source_path)
        label = Path(file.filename).stem
        display_label: str | None = label
    else:
        source = url
        label = url
        display_label = None  # pra links, vale o título do vídeo que o yt-dlp encontrar

    options = Options(
        num_clips=num_clips,
        min_len=min_len,
        max_len=max_len,
        mode=mode,
        whisper_model=model,
        language=language or None,
        captions=captions,
        max_minutes=cfg["max_minutes"],
    )
    with _lock:
        _jobs[job_id] = {
            "id": job_id,
            "status": "queued",
            "stage": "queued",
            "progress": 0.0,
            "message": "Na fila…",
            "error": "",
            "title": label,
            "clips": [],
            "created": time.time(),
        }
    _pool.submit(_run_job, job_id, source, options, job_dir, display_label)
    return {"id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Esse trabalho não existe mais. Os arquivos ficam disponíveis por tempo limitado.")
        return _public(job)


@app.get("/api/files/{job_id}/{name}")
def get_file(job_id: str, name: str) -> FileResponse:
    if not re.fullmatch(r"[a-f0-9]{12}", job_id) or not SAFE_NAME.match(name):
        raise HTTPException(404, "Arquivo não encontrado.")
    path = _settings()["data_dir"] / job_id / "clips" / name
    if not path.is_file():
        raise HTTPException(404, "Arquivo não encontrado. Ele pode ter expirado.")
    return FileResponse(path, media_type="video/mp4", filename=name)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")
