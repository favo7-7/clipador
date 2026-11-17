FROM python:3.11-slim

# FFmpeg faz os cortes; as fontes são usadas na legenda queimada no vídeo.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-liberation fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces roda como usuário 1000; outros hosts também aceitam.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    CLIPADOR_DATA=/home/user/data \
    CLIPADOR_DEBUG=0 \
    CLIPADOR_MODEL=tiny \
    CLIPADOR_MAX_MINUTES=5 \
    CLIPADOR_MAX_UPLOAD_MB=100
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

# Baixa o modelo de transcrição na hora do build, pra o primeiro pedido não ficar esperando.
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('tiny', device='cpu', compute_type='int8')"

ENV PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uvicorn clipador.web.server:app --host 0.0.0.0 --port ${PORT}"]
