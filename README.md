# Clipador

Site que transforma um vídeo longo em cortes verticais (9:16) prontos pra TikTok, Reels e Shorts.
Você envia um arquivo (ou cola um link), e ele devolve os trechos mais fortes, com legenda palavra por palavra.

## Como funciona

1. **Entrada:** arquivo de vídeo ou link (baixado com `yt-dlp`).
2. **Transcrição:** `faster-whisper` transcreve a fala com o tempo de cada palavra. Roda no próprio servidor, sem API paga.
3. **Escolha dos trechos:** cada janela de fala recebe uma nota que combina volume do áudio, ritmo da fala,
   exclamações/perguntas, palavras de impacto e um gancho no começo. Os melhores trechos que não se sobrepõem são escolhidos.
   - Se o vídeo **não tem fala** (gameplay, trailer), a escolha usa só os picos de volume.
   - Opcional: com `ANTHROPIC_API_KEY` definida, uma IA da Anthropic lê a transcrição e escolhe os trechos (cai na heurística se falhar).
4. **Corte:** `FFmpeg` recorta, converte pra 1080x1920 (preenchendo a tela ou com fundo desfocado) e queima a legenda.
5. **Web:** API em FastAPI com fila (um vídeo por vez), limites de tamanho/duração e limpeza automática dos arquivos.

## Rodar no seu PC (Windows)

1. Instale o **Python 3.11 ou 3.12** em python.org (marque "Add Python to PATH").
2. Instale o **FFmpeg**. No PowerShell: `winget install Gyan.FFmpeg`. Depois feche e abra o terminal.
   Teste com `ffmpeg -version`.
3. Na pasta do projeto:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m clipador serve
```

4. Abra http://127.0.0.1:8000 no navegador.

Na primeira transcrição o modelo do Whisper é baixado (algumas centenas de MB). Depois fica em cache.

### Pela linha de comando (sem o site)

```
python -m clipador run "https://..." -n 5 --min 20 --max 45
python -m clipador run meu_video.mp4 --mode blur --lang pt
```

Os clipes vão pra `saida/clips`. Rode `python -m clipador run --help` pra ver todas as opções.

## Publicar de graça (link pro currículo)

### Opção 1: Render (plano gratuito, sem cartão)

O `Dockerfile` já vem ajustado pra servidores pequenos: modelo de transcrição `tiny`, vídeos de até 5 minutos e arquivos de até 100 MB.

1. Suba o projeto no GitHub (seção abaixo).
2. Em render.com, crie a conta entrando com o GitHub.
3. **New + > Web Service**, escolha o repositório `clipador`, deixe o ambiente como **Docker** e o tipo de instância **Free**.
4. Clique em **Create Web Service** e acompanhe a aba **Logs**. O primeiro build leva alguns minutos.
5. O link fica no formato `https://clipador-xxxx.onrender.com`.

Pontos de atenção (confira os limites atuais em render.com):

- O plano gratuito tem pouca memória (512 MB). Se o processamento falhar por falta de memória, o servidor precisa de mais RAM ou o vídeo precisa ser mais curto.
- Ele "dorme" depois de uns 15 minutos sem uso, e a primeira visita demora cerca de 1 minuto pra acordar.

### Opção 2: Hugging Face Spaces

Em novembro de 2026, criar um Space com **Docker** pede plano pago (PRO) ou crédito na conta; só o tipo Estático é gratuito. Se você tiver plano pago, os passos são:

1. Crie uma conta em huggingface.co e depois um **New Space**: nome `clipador`, SDK **Docker**, template **Blank**, hardware **CPU basic (free)**.
2. No começo do `README.md` do Space, cole este bloco (ele diz ao Hugging Face qual porta usar):

```
---
title: Clipador
emoji: 🎬
colorFrom: red
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---
```

3. Envie os arquivos do projeto pro repositório do Space (pelo `git push`, igual ao GitHub, ou pelo botão *Files > Add file > Upload*).
4. Espere o *Build* terminar (alguns minutos: ele instala o FFmpeg e baixa o modelo). O link fica em `https://SEU-USUARIO-clipador.hf.space`.

Pontos de atenção:

- Num servidor gratuito, transcrever um vídeo de 10 a 15 minutos pode levar alguns minutos. A página mostra o andamento.
- O Space gratuito pode "dormir" quando fica um tempo sem uso, e a primeira visita demora pra acordar. Vale abrir o link antes de mandar pra alguém.
- **Links de YouTube podem falhar em servidor de nuvem**, porque o YouTube bloqueia muitos IPs de datacenter. O envio de **arquivo** é o caminho confiável.
  Se quiser desligar a aba de links no deploy, defina a variável `CLIPADOR_ALLOW_URL=0`.

### Variáveis de ambiente

| Variável | Padrão | O que faz |
|---|---|---|
| `CLIPADOR_MAX_UPLOAD_MB` | 300 | Tamanho máximo do arquivo enviado |
| `CLIPADOR_MAX_MINUTES` | 15 | Duração máxima do vídeo |
| `CLIPADOR_MAX_QUEUE` | 4 | Pedidos simultâneos (fila + em andamento) |
| `CLIPADOR_TTL_SECONDS` | 3600 | Tempo até os arquivos serem apagados |
| `CLIPADOR_MODEL` | base | Modelo do Whisper (`tiny`, `base`, `small`) |
| `CLIPADOR_ALLOW_URL` | 1 | `0` desativa o envio por link |
| `CLIPADOR_DEBUG` | 1 | `1` mostra o erro técnico na página (bom no seu PC). No Docker já vem `0`, pra não expor detalhes do servidor |
| `ANTHROPIC_API_KEY` | (vazio) | Ativa a escolha de trechos por IA (uso pago da API) |

## Subir no GitHub

```
git init
git add .
git commit -m "primeira versão do Clipador"
git branch -M main
git remote add origin https://github.com/SEU-USUARIO/clipador.git
git push -u origin main
```

Depois, no repositório do GitHub, coloque o link do site no campo *About > Website*.

## Usar o chat da live (picos de comentários)

Quando muita gente comenta ao mesmo tempo, normalmente aconteceu algo importante. O Clipador soma a reação da
audiência à nota de cada trecho, junto com volume, ritmo da fala e palavras de impacto. Como o chat reage alguns
segundos **depois** do acontecimento, ele volta 8 segundos pra o corte pegar o lance inteiro.

- **Link de live ou replay do YouTube:** é automático. Ele tenta baixar o chat do replay e o gráfico "mais revisto"
  do vídeo; se não existir, segue sem. Exemplo: `python -m clipador run "https://youtube.com/watch?v=..." -n 10`
- **Arquivo de chat (Twitch, ou outro):** `python -m clipador run video.mp4 --chat chat.json`. Formatos aceitos:
  JSON do TwitchDownloader, `.live_chat.json` do yt-dlp, ou um `.txt`/`.csv` com um tempo em segundos por linha
  (`123.4` ou `123.4,mensagem`). Precisa de pelo menos 20 mensagens.
- **Desligar:** `--no-audience`.

Esse recurso funciona na linha de comando e no site local. No site publicado (servidor pequeno) ele fica desligado.

## Testes

```
pip install -r requirements-dev.txt
python -m pytest
```

Os testes geram um vídeo de exemplo com FFmpeg e cobrem a escolha dos trechos, as legendas, o corte vertical,
o pipeline completo e a API (upload, limites, fila e bloqueio de endereços internos).

## Direitos autorais

Use só vídeos seus, de quem autorizou ou com licença que permita reuso. Postar cortes de conteúdo alheio sem permissão
pode gerar remoção de vídeo e punição na conta, e o TikTok reduz o alcance de conteúdo não original.

## Estrutura

```
clipador/
  downloader.py   baixa o vídeo (e barra endereços internos)
  transcribe.py   Whisper com tempo por palavra
  audio.py        volume do áudio segundo a segundo
  highlights.py   escolha dos melhores trechos
  subtitles.py    legenda ASS palavra por palavra
  cutter.py       corte vertical com FFmpeg
  pipeline.py     junta tudo
  cli.py          comando `python -m clipador`
  web/            servidor FastAPI e a página
tests/
Dockerfile
```
