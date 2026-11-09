"""Mensagens, cores e embeds temáticos da Yuna (SAO: Ordinal Scale).

Toda a "voz" da Yuna mora aqui: personalidade, paleta e formatos visuais.
Este módulo NÃO contém lógica de reprodução — apenas apresentação.
"""

from __future__ import annotations

import math
from typing import List, Optional

import discord

from utils.queue import Song

# ── Paleta da Yuna ───────────────────────────────────────────────────────────
PINK = 0xFF9EC4    # rosa — cor PADRÃO da Yuna
LILAC = 0xC8A2FF   # lilás — usado em erros e na fila
CYAN = 0x9EE7FF    # ciano — usado em ajustes técnicos (volume / loops)

DEFAULT_COLOR = PINK

# Itens exibidos por página no !queue
QUEUE_PAGE_SIZE = 10

# ── Frases temáticas (exatamente como a Yuna fala) ──────────────────────────
ON_READY = "Yuna despertou. As memórias estão prontas para serem cantadas. 🎶"
ENTERING_VOICE = "Yuna está aqui. Qual memória vamos cantar hoje?"
NOW_PLAYING = "Invocando a memória de *{titulo}*..."
PAUSED = "Silêncio... guardando essa memória."
RESUMED = "A melodia continua."
SKIPPED = "Essa memória ficou para trás."
STOPPED = "Até a próxima memória. Sorria. 🌸"
PLAYLIST_ADDED = "Mais {n} memórias foram guardadas na fila."
QUEUE_EMPTY = "As memórias desta sessão terminaram. 🌸"
INVALID_URL = "Não consegui acessar essa memória agora... tente novamente?"
YOUTUBE_BLOCKED = "O YouTube está resistindo às minhas canções. Verifique os cookies da Yuna."
NOT_IN_VOICE = "Entre em um canal de voz para que eu possa cantar com você."

# ── Frases de apoio (mensagens complementares) ──────────────────────────────
QUEUE_CLEARED = "Todas as memórias em espera foram liberadas. ✨"
EMPTY_QUEUE = "A fila está vazia... nenhuma memória aguardando por agora. 🌙"
NOTHING_PLAYING = "Nada está tocando no momento. Que tal uma canção nova? 🎵"
ALREADY_PAUSED = "Essa memória já está silenciada. 🤫"
ALREADY_RESUMED = "A melodia já está fluindo. ♪"
CONNECT_FAILED = "Não consegui entrar no canal de voz... tenta de novo, por favor? 🥺"
VOLUME_SET = "Volume ajustado para {pct}% 🎚️"
VOLUME_HINT = "Me dê um número de 0 a 200... posso cantar baixinho ou com toda a voz. 🎹"
LOOP_ON = "Loop ativado para a memória atual. 🔁"
LOOP_OFF = "Loop desativado. A memória seguirá o fluxo natural. 🌤️"
LOOP_QUEUE_ON = "Loop da fila ativado. Todas as memórias ressurgirão em sequência. 🔂"
LOOP_QUEUE_OFF = "Loop da fila desativado."
GENERIC_ERROR = "Algo estranho aconteceu durante a canção... tenta de novo em instantes? 🥺"
FFMPEG_MISSING = "FFmpeg não encontrado no sistema... instala com `winget install --id Gyan.FFmpeg` (ou o comando do README) e roda o bot de novo? 🎹"
USAGE_HINT = "Hmm... confira o uso do comando — use !help para ver os exemplos. 📜"


# ── Formatadores auxiliares ─────────────────────────────────────────────────
def format_duration(seconds: Optional[float]) -> str:
    """Formata segundos em `mm:ss` ou `h:mm:ss`. `None` = ao vivo/desconhecido."""
    if seconds is None:
        return "ao vivo 🎙️"
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


# ── Construtores de embed ───────────────────────────────────────────────────
def make_embed(title: str, description: Optional[str] = None, color: int = DEFAULT_COLOR) -> discord.Embed:
    """Embed base com a assinatura da Yuna no rodapé."""
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text="Yuna • a cantora virtual de SAO 💗")
    return embed


def info_embed(text: str, title: str = "Yuna 🎵", color: int = DEFAULT_COLOR) -> discord.Embed:
    """Embed informativo simples (uma frase da Yuna)."""
    return make_embed(title, text, color)


def error_embed(text: str, title: str = "Memória interrompida ✖") -> discord.Embed:
    """Embed de erro, sempre em lilás para diferenciar visualmente."""
    return make_embed(title, text, LILAC)


def now_playing_embed(song: Song, title: str = "🎶 Tocando agora") -> discord.Embed:
    """Embed de música atual: título, duração, thumbnail e quem pediu."""
    embed = make_embed(title, NOW_PLAYING.format(titulo=song.title), DEFAULT_COLOR)
    if song.webpage_url:
        embed.url = song.webpage_url
    embed.add_field(name="Duração", value=format_duration(song.duration), inline=True)
    embed.add_field(name="Pedida por", value=song.requester, inline=True)
    if song.thumbnail:
        embed.set_thumbnail(url=song.thumbnail)
    return embed


def queued_embed(song: Song, position: int) -> discord.Embed:
    """Confirmação de música adicionada à fila (posições 1-based)."""
    embed = make_embed("💾 Memória guardada", f"*{song.title}* entrou na fila na posição **{position}**.")
    if song.webpage_url:
        embed.url = song.webpage_url
    if song.thumbnail:
        embed.set_thumbnail(url=song.thumbnail)
    embed.add_field(name="Duração", value=format_duration(song.duration), inline=True)
    embed.add_field(name="Pedida por", value=song.requester, inline=True)
    return embed


def playlist_added_embed(n: int, first: Optional[Song] = None) -> discord.Embed:
    """Confirmação de playlist inteira enfileirada."""
    lines: List[str] = [PLAYLIST_ADDED.format(n=n)]
    if first is not None:
        lines.insert(0, f"Começando por *{first.title}*...")
    return make_embed("💾 Playlist guardada", "\n".join(lines))


def queue_embed(current: Optional[Song], incoming: List[Song], page: int = 1) -> discord.Embed:
    """Embed paginado da fila (padrão: 10 itens por página, !queue <n> navega)."""
    total = len(incoming)
    pages = max(1, math.ceil(total / QUEUE_PAGE_SIZE))
    page = min(max(1, page), pages)

    lines: List[str] = []
    if current is not None:
        lines.append(f"▶️ **Agora:** {current.title} — `{format_duration(current.duration)}`")
    else:
        lines.append("▶️ **Agora:** *(a memória está terminando...)*")

    chunk = incoming[(page - 1) * QUEUE_PAGE_SIZE : page * QUEUE_PAGE_SIZE]
    if chunk:
        for off, song in enumerate(chunk):
            pos = (page - 1) * QUEUE_PAGE_SIZE + off + 1
            lines.append(f"`{pos:>3}.` {song.title} — `{format_duration(song.duration)}`")
    elif current is None:
        lines.append("*(nenhuma memória aguardando)*")

    embed = make_embed("🌙 Fila de memórias", "\n".join(lines), LILAC)
    embed.set_footer(text=f"Página {page}/{pages} • {total} memória(s) aguardando • use !queue <n> para navegar")
    return embed


def help_embed() -> discord.Embed:
    """Resumo de todos os comandos, no tom da Yuna."""
    body = (
        "**🎵 Música**\n"
        "`!play <url_ou_busca>` — toca um vídeo, uma playlist inteira ou o resultado da busca\n"
        "`!pause` / `!resume` — guarda / retoma a memória atual\n"
        "`!skip` — deixa essa memória para trás\n"
        "`!stop` — encerra a sessão e esvazia a fila\n"
        "`!leave` — Yuna sai do canal de voz\n\n"
        "**🌙 Fila**\n"
        "`!queue [página]` — mostra a fila em páginas de 10\n"
        "`!nowplaying` — a memória que está cantando agora\n"
        "`!clear` — libera todas as memórias em espera\n"
        "`!loop` — repete a memória atual\n"
        "`!loopqueue` — repete a fila inteira\n\n"
        "**🎚️ Ajustes**\n"
        "`!volume <0-200>` — volume da canção\n\n"
        "Dica: busca funciona direto — ex. `!play Sword Art Online Ordinal Scale soundtrack` 💗"
    )
    return make_embed("Shall we sing, player? 💗", body, CYAN)
