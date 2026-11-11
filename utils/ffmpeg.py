"""Localização do FFmpeg do sistema (independente do PATH do terminal).

Motivação: após winget/apt instalar o FFmpeg, terminais JÁ ABERTOS ainda usam
o PATH antigo — e o discord.py só procura 'ffmpeg' no PATH, quebrando o play.
Aqui procuramos o executável em todos os locais conhecidos e devolvemos o
caminho pronto para `FFmpegPCMAudio(executable=...)`.
"""

from __future__ import annotations

import glob
import os
import shutil
from typing import Optional

_cache: Optional[str] = None


def _first_existing(paths: list[str]) -> Optional[str]:
    for path in paths:
        if path and os.path.isfile(path):
            return path
    return None


def find_ffmpeg(force: bool = False) -> Optional[str]:
    """Devolve o caminho do ffmpeg.exe (ou None se não existir em lugar algum).

    Ordem de busca:
      1. PATH do processo (shutil.which) — cobre instalação clássica;
      2. Alias do WinGet (%LOCALAPPDATA%\\Microsoft\\WinGet\\Links);
      3. Pacote Gyan.FFmpeg dentro de WinGet\\Packages (qualquer versão).
    A busca roda UMA vez e o resultado fica em cache (sem custo por música).
    """
    global _cache
    if _cache is not None and not force:
        return _cache

    found = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if found:
        _cache = found
        return found

    local_app = os.getenv("LOCALAPPDATA") or ""

    # Alias criado pelo winget para pacotes com "portable command alias"
    alias = _first_existing(
        [
            os.path.join(local_app, "Microsoft", "WinGet", "Links", "ffmpeg.exe"),
        ]
    )
    if alias:
        _cache = alias
        return alias

    # Instalação Gyan.FFmpeg via winget (zip extraído em Packages\Gyan.FFmpeg_*\...)
    winget_packages = os.path.join(local_app, "Microsoft", "WinGet", "Packages")
    gyan = glob.glob(os.path.join(winget_packages, "Gyan.FFmpeg*", "*", "bin", "ffmpeg.exe"))
    candidate = _first_existing(gyan)
    if candidate:
        _cache = candidate
        return candidate

    return None


def ensure_deno_path() -> bool:
    """Garante que o deno (runtime JS exigido pelo yt-dlp/EJS) esteja no PATH.

    O YouTube roda um desafio `n` de assinatura que o yt-dlp resolve com um
    runtime JavaScript (EJS + deno). Sem ele, os formatos de áudio são
    DESCARTADOS e o play falha com 'Requested format is not available'.

    O winget instala o deno em `Packages\\DenoLand.Deno*\\` SEM alias
    confiável no `Links` — e o yt-dlp sonda o PATH do processo a cada
    extração. Aqui colocamos o diretório dele no PATH do processo
    (idempotente; segue a mesma tática do find_ffmpeg para o ffmpeg).
    """
    if shutil.which("deno"):
        return True

    local_app = os.getenv("LOCALAPPDATA") or ""
    winget_packages = os.path.join(local_app, "Microsoft", "WinGet", "Packages")
    deno = glob.glob(os.path.join(winget_packages, "DenoLand.Deno*", "deno.exe"))
    candidate = _first_existing(deno)
    if candidate is None:
        return False

    os.environ["PATH"] = os.path.dirname(candidate) + os.pathsep + os.environ.get("PATH", "")
    return True
