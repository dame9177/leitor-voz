"""Command line: run the daemon, or send it commands (used by the GNOME shortcut)."""

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

from .config import Settings


def _url(path: str) -> str:
    return f"http://127.0.0.1:{Settings.load().port}{path}"


def _call(path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        _url(path), data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def _notify(message: str) -> None:
    print(message, file=sys.stderr)
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "Leitor de voz", "Leitor de voz", message], check=False)


def _ensure_daemon() -> bool:
    """Start the daemon in the background if it isn't running yet."""
    try:
        _call("/status")
        return True
    except (urllib.error.URLError, OSError):
        pass
    subprocess.Popen(
        [sys.executable, "-m", "leitor"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        time.sleep(0.2)
        try:
            _call("/status")
            return True
        except (urllib.error.URLError, OSError):
            continue
    return False


def _read(text: str) -> int:
    if not text.strip():
        _notify("Nenhum texto selecionado.")
        return 1
    if not _ensure_daemon():
        _notify("Não consegui iniciar o leitor.")
        return 1
    _call("/read", {"text": text})
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="leitor", description="Leitor de voz para estudo.")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("daemon", help="roda o app (padrão sem argumentos)")
    sub.add_parser("ler-selecao", help="lê o texto selecionado em qualquer programa (X11)")
    ler = sub.add_parser("ler", help="lê o texto dado (ou da entrada padrão)")
    ler.add_argument("texto", nargs="*")
    sub.add_parser("pausar", help="pausa ou retoma")
    sub.add_parser("parar", help="para a leitura")
    sub.add_parser("proximo", help="pula para o próximo trecho")
    sub.add_parser("status", help="mostra o estado atual")
    args = parser.parse_args(argv)

    if args.cmd in (None, "daemon"):
        from .app import run_daemon

        return run_daemon()
    if args.cmd == "ler-selecao":
        from .selection import read_primary_selection

        return _read(read_primary_selection())
    if args.cmd == "ler":
        return _read(" ".join(args.texto) if args.texto else sys.stdin.read())

    actions = {"pausar": "toggle", "parar": "stop", "proximo": "next"}
    try:
        if args.cmd == "status":
            print(json.dumps(_call("/status"), ensure_ascii=False, indent=2))
        else:
            _call("/control", {"action": actions[args.cmd]})
    except (urllib.error.URLError, OSError):
        _notify("O leitor não está rodando. Inicie com: leitor")
        return 1
    return 0
