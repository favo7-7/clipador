"""Linha de comando: `python -m clipador run <link-ou-arquivo>` e `python -m clipador serve`."""

from __future__ import annotations

import argparse
import sys

from .cutter import MODES
from .pipeline import Options, process
from .utils import ClipadorError, fmt_time


def _print_progress(stage: str, fraction: float, message: str) -> None:
    end = "\n" if fraction >= 1.0 else ""
    print(f"\r[{fraction * 100:5.1f}%] {message:<48}", end=end, flush=True)


def _cmd_run(args: argparse.Namespace) -> int:
    options = Options(
        num_clips=args.num,
        min_len=args.min,
        max_len=args.max,
        mode=args.mode,
        whisper_model=args.model,
        language=args.lang,
        captions=not args.no_captions,
        use_claude=not args.no_claude,
        max_minutes=args.max_minutes,
        use_audience=not args.no_audience,
        chat_file=args.chat,
    )
    try:
        title, clips = process(args.source, args.out, options, _print_progress)
    except ClipadorError as exc:
        print(f"\nErro: {exc}", file=sys.stderr)
        return 1

    print(f"\n{title}\n")
    for clip in clips:
        print(
            f"  {clip.file}\n"
            f"    {fmt_time(clip.start)} - {fmt_time(clip.end)}  |  nota {clip.score:.0f}  |  {clip.reason}"
        )
    print(f"\nClipes salvos em: {args.out}/clips")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("clipador.web.server:app", host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="clipador",
        description="Transforma vídeos longos em cortes verticais (9:16) com legenda.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="gera os cortes a partir de um link ou arquivo")
    run.add_argument("source", help="link do vídeo ou caminho de um arquivo")
    run.add_argument("-o", "--out", default="saida", help="pasta de saída (padrão: saida)")
    run.add_argument("-n", "--num", type=int, default=5, help="quantos clipes gerar (padrão: 5)")
    run.add_argument("--min", type=float, default=20.0, help="duração mínima de cada clipe, em segundos")
    run.add_argument("--max", type=float, default=55.0, help="duração máxima de cada clipe, em segundos")
    run.add_argument("--mode", choices=list(MODES), default="fill", help="enquadramento vertical")
    run.add_argument("--model", default="base", help="modelo do Whisper: tiny, base, small, medium")
    run.add_argument("--lang", default=None, help="idioma da fala (pt, en, es...). Padrão: detectar")
    run.add_argument("--no-captions", action="store_true", help="não queimar legendas")
    run.add_argument("--no-claude", action="store_true", help="não usar a IA da Anthropic pra escolher trechos")
    run.add_argument("--max-minutes", type=float, default=None, help="recusar vídeos mais longos que isso")
    run.add_argument("--chat", default=None, help="arquivo com o chat da live (pesa na escolha dos trechos)")
    run.add_argument("--no-audience", action="store_true", help="não buscar chat/'mais revisto' automaticamente")
    run.set_defaults(func=_cmd_run)

    serve = sub.add_parser("serve", help="sobe o site (interface web) no seu computador")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=_cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
