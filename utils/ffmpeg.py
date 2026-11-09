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
