"""Extração de fontes de áudio via yt-dlp, com prevenção anti-bloqueio do YouTube.

Pontos críticos de sobrevivência contra o YouTube:
  • `cookiefile` (cookies.txt em formato Netscape) → evade "Sign in to confirm
    you're not a bot" na maioria dos casos;
  • `source_address: "0.0.0.0"` → força IPv4 IGUALMENTE no download e nas
    requisições de suporte, evita glitches com IPv6;
  • `extract_flat: "in_playlist"` → playlists inteiras listadas em segundos,
    com stream resolvido apenas na hora do play (via `resolve_stream`);
  • flags `-reconnect` no FFmpeg (definidas no cog) → recupera streams derrubados.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from yt_dlp import DownloadError, YoutubeDL

from utils import messages
from utils.queue import Song

log = logging.getLogger("yuna.ytdl")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Arquivo de cookies, em formato Netscape (renomeável via .env → YUNA_COOKIES_FILE)
COOKIES_FILE: Path = Path(os.getenv("YUNA_COOKIES_FILE", str(_PROJECT_ROOT / "cookies.txt")))

# Avaliado na importação: existência de cookies (evita crash — só avisa depois)
COOKIES_AVAILABLE: bool = COOKIES_FILE.is_file()

# Guarda para o aviso no console acontecer UMA única vez por sessão
_COOKIE_WARNED: bool = False


def warn_if_no_cookies() -> None:
    """Avisa no console se cookies.txt estiver ausente. NUNCA derruba o bot."""
    global _COOKIE_WARNED
    if not COOKIES_AVAILABLE and not _COOKIE_WARNED:
        _COOKIE_WARNED = True
        log.warning(
            "cookies.txt não encontrado em '%s' — a Yuna segue SEM cookies, mas o "
            "YouTube pode responder 'Sign in to confirm you're not a bot'. "
            "Gere o arquivo seguindo o README (extensão Get cookies.txt LOCALLY).",
            str(COOKIES_FILE),
        )


class SourceError(Exception):
    """Memória inacessível: URL inválida, vídeo removido, rede indisponível, etc."""


class BlockedError(SourceError):
    """YouTube resistindo: precisa de cookies válidos (e/ou PO Token)."""


# ── Opções base do yt-dlp (anti-bloqueio) ───────────────────────────────────
_BASE_OPTS: Dict[str, Any] = {
    "format": "bestaudio/best",      # melhor faixa de áudio disponível
    "noplaylist": False,             # aceita PLAYLIST completa (enfileira tudo)
    "quiet": True,
    "no_warnings": True,
    "extract_flat": "in_playlist",   # lista playlists rápido; vídeos individuais continuam completos
    "source_address": "0.0.0.0",     # força IPv4 em todas as conexões
    "default_search": "error",       # evita extrair tags aleatórias como se fossem URL
}
if COOKIES_AVAILABLE:
    _BASE_OPTS["cookiefile"] = str(COOKIES_FILE)

_YTDLP: Optional[YoutubeDL] = None


def _get_ytdlp() -> YoutubeDL:
    """Singleton do YoutubeDL (padrão do discord.py da vida real — barato e reusável)."""
    global _YTDLP
    if _YTDLP is None:
        _YTDLP = YoutubeDL(_BASE_OPTS)
    return _YTDLP


_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

# Sinais de que o YouTube está bloqueando por verificação de bot/idade
_BLOCK_HINTS = ("sign in", "confirm", "not a bot", "cookies", "login required")
_AGE_RE = re.compile(r"age[- ]restr", re.IGNORECASE)


def is_url(text: str) -> bool:
    """True se o texto parece uma URL http(s)."""
    return _URL_RE.match(text.strip()) is not None


def _raise_for(download_error: DownloadError) -> None:
    """Classifica erros do yt-dlp: bloqueio do YouTube × memória inválida."""
    text = str(download_error).lower()
    if any(hint in text for hint in _BLOCK_HINTS) or _AGE_RE.search(text):
        raise BlockedError(messages.YOUTUBE_BLOCKED) from download_error
    log.warning("yt-dlp falhou na extração: %s", str(download_error)[:300])
    raise SourceError(messages.INVALID_URL) from download_error


async def _extract(query: str) -> Optional[Dict[str, Any]]:
    """Roda `extract_info` do yt-dlp em thread separada (não bloqueia o loop)."""
    ytdlp = _get_ytdlp()
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            None, functools.partial(ytdlp.extract_info, query, download=False)
        )
    except DownloadError as exc:
        _raise_for(exc)
        return None  # inalcançável (o raise acima sempre acontece)


def _first_url(info: Dict[str, Any]) -> str:
    """Descobre o link público a partir de um registro do yt-dlp."""
    for key in ("webpage_url", "original_url", "url"):
        value = info.get(key)
        if value and str(value).startswith("http"):
            return str(value)
    video_id = info.get("id")
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    return ""


def _first_thumbnail(info: Dict[str, Any]) -> Optional[str]:
    """Thumbnail de melhor resolução disponível (ou None)."""
    thumb = info.get("thumbnail")
    if isinstance(thumb, str) and thumb:
        return thumb
    for item in reversed(info.get("thumbnails") or []):
        url = item.get("url") if isinstance(item, dict) else None
        if url and str(url).startswith("http"):
            return str(url)
    return None


def _pull_stream_url(info: Dict[str, Any]) -> Optional[str]:
    """Extrai a URL direta de áudio de um vídeo já resolvido por completo."""
    stream = info.get("url")
    if isinstance(stream, str) and stream:
        return stream
    formats = info.get("formats") or []
    # 1ª passada: prefere formatos apenas-áudio (menos bytes, mesmo som)
    for fmt in reversed(formats):
        if fmt.get("url") and fmt.get("acodec") not in (None, "none"):
            return str(fmt["url"])
    # 2ª passada: qualquer formato com URL (streams "ao vivo", por exemplo)
    for fmt in reversed(formats):
        if fmt.get("url"):
            return str(fmt["url"])
    return None


def _duration_or_none(info: Dict[str, Any]) -> Optional[float]:
    """Duração em segundos, ou None se ao vivo/indeterminada."""
    if info.get("is_live") or info.get("is_live_content"):
        return None
    value = info.get("duration")
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return None


def _make_song(data: Dict[str, Any], requester: str, with_stream: bool) -> Song:
    """Converte um registro do yt-dlp em `Song` (com ou sem stream pronto)."""
    return Song(
        title=str(data.get("title") or "Memória sem título"),
        webpage_url=_first_url(data),
        stream_url=_pull_stream_url(data) if with_stream else None,
        duration=_duration_or_none(data),
        thumbnail=_first_thumbnail(data),
        requester=requester,
    )


def _songs_from_playlist(info: Dict[str, Any], requester: str) -> List[Song]:
    """Converte TODAS as entries de uma playlist em Songs (extração flat)."""
    songs: List[Song] = []
    for entry in info.get("entries") or []:
        if not entry:
            continue  # entradas inválidas são puladas (típico de vídeos deletados)
        song = _make_song(entry, requester, with_stream=False)
        if song.webpage_url:
            songs.append(song)
        else:
            log.warning("Entry sem URL identificável em playlist: %r", entry)
    return songs


async def search(query: str, requester: str) -> List[Song]:
    """Resolve o pedido do usuário e devolve de 1 a N músicas prontas para a fila.

    Comportamento:
      • URL de vídeo único  → 1 Song com stream já resolvido;
      • URL de PLAYLIST     → TODAS as entries (extração flat, stream depois);
      • texto de busca      → melhor resultado via `ytsearch`.
    """
    query = query.strip()
    if not query:
        raise SourceError(messages.INVALID_URL)

    if is_url(query):
        info = await _extract(query)
        if info is None:
            raise SourceError(messages.INVALID_URL)
        if info.get("_type") == "playlist":
            # IMPORTANTE: com noplaylist=False, uma URL ?v=...&list=... também
            # cai aqui e enfileira a playlist inteira.
            songs = _songs_from_playlist(info, requester)
            if not songs:
                raise SourceError(messages.INVALID_URL)
            log.info("Playlist '%s' enfileirada: %d vídeo(s)", info.get("title"), len(songs))
            return songs
        return [_make_song(info, requester, with_stream=True)]

    # ── Busca nominal via ytsearch ───────────────────────────────────────────
    results = await _extract(f"ytsearch1:{query}")
    entries = (results or {}).get("entries") or []
    first = next((entry for entry in entries if entry), None)
    if first is None:
        raise SourceError(messages.INVALID_URL)

    # A entry da busca é "flat": resolve o vídeo escolhido por completo.
    info = await _extract(_first_url(first))
    if info is None:
        raise SourceError(messages.INVALID_URL)
    if info.get("_type") == "playlist":
        songs = _songs_from_playlist(info, requester)
        if not songs:
            raise SourceError(messages.INVALID_URL)
        return songs
    return [_make_song(info, requester, with_stream=True)]


async def resolve_stream(song: Song) -> str:
    """Garante a URL direta de áudio da Song (exigida pelo FFmpeg do discord.py).

    Entradas de playlist/salvas como "flat" vêm sem stream — aqui elas são
    resolvidas na hora, porque URLs do YouTube expiram rapidamente.
    """
    if song.stream_url:
        return song.stream_url

    if not song.webpage_url:
        raise SourceError(messages.INVALID_URL)

    info = await _extract(song.webpage_url)
    # Numa extração completa, vídeo único nunca vira playlist — mas por segurança:
    if info is None or info.get("_type") == "playlist":
        raise SourceError(messages.INVALID_URL)

    stream = _pull_stream_url(info)
    if not stream:
        raise SourceError(messages.INVALID_URL)

    # Metadados podem ser melhores/diferentes desde a extração flat: atualiza.
    song.title = str(info.get("title") or song.title)
    song.duration = _duration_or_none(info) or song.duration
    song.thumbnail = _first_thumbnail(info) or song.thumbnail
    song.stream_url = stream
    return stream
