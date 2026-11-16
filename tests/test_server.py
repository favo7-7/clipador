import time

import pytest
from fastapi.testclient import TestClient

from clipador import pipeline
from clipador.downloader import validate_public_url
from clipador.utils import ClipadorError


@pytest.fixture
def client(tmp_path, monkeypatch, transcript):
    monkeypatch.setenv("CLIPADOR_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CLIPADOR_MAX_UPLOAD_MB", "5")
    monkeypatch.setattr(pipeline, "transcribe_video", lambda *a, **k: transcript)
    from clipador.web import server

    server._jobs.clear()
    return TestClient(server.app)


def _wait(client, job_id, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.5)
    raise AssertionError("job não terminou a tempo")


def test_index_and_health(client):
    assert "Clipador" in client.get("/").text
    health = client.get("/api/health").json()
    assert health["ok"] and health["max_upload_mb"] == 5


def test_requires_exactly_one_source(client):
    assert client.post("/api/jobs", data={}).status_code == 400
    r = client.post("/api/jobs", data={"url": "https://example.com/v"}, files={"file": ("a.mp4", b"x", "video/mp4")})
    assert r.status_code == 400


def test_rejects_bad_extension_and_bad_options(client):
    r = client.post("/api/jobs", files={"file": ("virus.exe", b"x", "application/octet-stream")})
    assert r.status_code == 400
    r = client.post("/api/jobs", data={"num_clips": 99}, files={"file": ("a.mp4", b"x", "video/mp4")})
    assert r.status_code == 400
    r = client.post("/api/jobs", data={"mode": "zoom"}, files={"file": ("a.mp4", b"x", "video/mp4")})
    assert r.status_code == 400


def test_rejects_oversized_upload(client):
    big = b"0" * (6 * 1024 * 1024)
    r = client.post("/api/jobs", files={"file": ("big.mp4", big, "video/mp4")})
    assert r.status_code == 413


def test_rejects_private_urls(client):
    for url in ("http://localhost/video", "http://127.0.0.1:8000/x", "http://169.254.169.254/latest"):
        r = client.post("/api/jobs", data={"url": url})
        assert r.status_code == 400, url
    with pytest.raises(ClipadorError):
        validate_public_url("ftp://example.com/file")


def test_full_flow_upload_to_download(client, sample_video, monkeypatch):
    monkeypatch.setenv("CLIPADOR_MAX_UPLOAD_MB", "100")
    with open(sample_video, "rb") as fh:
        r = client.post(
            "/api/jobs",
            data={"num_clips": 2, "min_len": 15, "max_len": 30},
            files={"file": ("meu video.mp4", fh, "video/mp4")},
        )
    assert r.status_code == 202
    job = _wait(client, r.json()["id"])
    assert job["status"] == "done", job
    assert job["clips"]

    url = job["clips"][0]["url"]
    full = client.get(url)
    assert full.status_code == 200 and full.headers["content-type"] == "video/mp4"
    assert len(full.content) > 10_000

    partial = client.get(url, headers={"Range": "bytes=0-99"})
    assert partial.status_code == 206 and len(partial.content) == 100

    # a pasta de trabalho e o upload original são apagados
    job_dir = client.get(url).request.url.path.split("/")[3]
    from clipador.web import server

    assert not (server._settings()["data_dir"] / job_dir / "upload").exists()


def test_file_endpoint_blocks_path_traversal(client):
    assert client.get("/api/files/abc/..%2f..%2fetc%2fpasswd").status_code == 404
    assert client.get("/api/files/aaaaaaaaaaaa/nao-existe.mp4").status_code == 404
    assert client.get("/api/files/aaaaaaaaaaaa/x.txt").status_code == 404
