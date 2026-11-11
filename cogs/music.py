"""Cog de música da Yuna: comandos e motor de reprodução por servidor.

Arquitetura do motor:
  • Uma fila `MusicQueue` por guild (dict[guild_id → fila]);
  • Transições de música são SERIALIZADAS por guild via `asyncio.Lock`
    (evita duas músicas no mesmo canal quando comandos se atropelam);
  • O encadeamento acontece no callback `after` do FFmpeg, que agenda a
    coroutine `_on_finished` no event loop do bot;
  • Streams de playlist são resolvidos SÓ na hora do play (URLs expiram).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional, Set

import discord
from discord.ext import commands

from utils import messages, ytdl
from utils.ffmpeg import find_ffmpeg
from utils.queue import MusicQueue, Song

log = logging.getLogger("yuna.music")

# FFmpeg re-conecta sozinho se o servidor do YouTube derrubar o áudio
FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

# Tipo do canal de voz aceito nos comandos
VoiceChannel = discord.VoiceChannel


class MusicCog(commands.Cog, name="Música"):
    """Tudo que a Yuna faz: fila, voz e comandos em um só lugar por servidor."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # Fila por servidor (chave: guild.id)
        self._queues: Dict[int, MusicQueue] = {}
        # Último canal de texto usado por server (para avisos do player)
        self._channels: Dict[int, Optional[discord.abc.Messageable]] = {}
        # Volume persistido por servidor (0.0 – 2.0)
        self._volumes: Dict[int, float] = {}
        # Serializa transições de música por servidor
        self._locks: Dict[int, asyncio.Lock] = {}
        # Servidores em !stop/!leave → suprime a mensagem de fila vazia
        self._stopping: Set[int] = set()
        # Aviso imediato no console se cookies.txt não existir (sem crashar)
        ytdl.warn_if_no_cookies()

    # ════════════════════════ Infra estrutura ════════════════════════
    def _queue(self, guild_id: int) -> MusicQueue:
        """Fila da guild, criada sob demanda."""
        if guild_id not in self._queues:
            self._queues[guild_id] = MusicQueue()
        return self._queues[guild_id]

    def _volume(self, guild_id: int) -> float:
        """Volume salvo da guild (padrão 100%)."""
        return self._volumes.get(guild_id, 1.0)

    def _remember_channel(self, ctx: commands.Context) -> None:
        """Lembra o canal de texto para os avisos vindos do callback `after`."""
        self._channels[ctx.guild.id] = ctx.channel

    async def _send(self, guild_id: int, embed: discord.Embed) -> None:
        """Envia num canal de texto memorizado; falhas não derrubam o player."""
        channel = self._channels.get(guild_id)
        if channel is None:
            log.warning("Sem canal de texto memorizado na guild %s; aviso descartado", guild_id)
            return
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as exc:
            log.warning("Falha ao enviar aviso na guild %s: %r", guild_id, exc)

    def _cleanup(self, guild_id: int) -> None:
        """Limpa estado da guild (fila/supressão). Executado ao sair de voz."""
        self._queues.pop(guild_id, None)
        self._channels.pop(guild_id, None)
        self._stopping.discard(guild_id)
        log.info("Estado de música limpo para a guild %s", guild_id)

    # ════════════════════════ Voz ═══════════════════════════════════
    def _author_voice(self, ctx: commands.Context) -> Optional[discord.VoiceChannel]:
        """Canal de voz do autor, se ele estiver conectado."""
        state = ctx.author.voice if hasattr(ctx.author, "voice") else None
        if state and state.channel:
            return state.channel
        return None

    async def _ensure_voice(self, ctx: commands.Context) -> Optional[discord.VoiceClient]:
        """Conecta a Yuna ao canal do autor (ou a move se já estiver em outro)."""
        vc: Optional[discord.VoiceClient] = ctx.guild.voice_client
        target = self._author_voice(ctx)
        if target is None:
            return None

        if vc and vc.is_connected():
            if vc.channel and vc.channel.id != target.id:
                await vc.move_to(target)
            return vc

        try:
            vc = await target.connect(timeout=30.0, reconnect=False)
            await ctx.send(embed=messages.info_embed(messages.ENTERING_VOICE))
            return vc
        except (asyncio.TimeoutError, discord.ClientException) as exc:
            log.warning("Falha ao conectar em voz na guild %s: %r", ctx.guild.id, exc)
            return None

    # ═══════════════════ Motor de reprodução ════════════════════════
    def _make_after(self, guild_id: int):
        """Callback `after` do FFmpeg: agenda `_on_finished` no event loop."""

        def _after(error: Optional[BaseException]) -> None:
            if error is not None:
                log.warning("Falha durante reprodução na guild %s: %r", guild_id, error)
            try:
                asyncio.run_coroutine_threadsafe(self._on_finished(guild_id), self.bot.loop)
            except (RuntimeError, AttributeError):  # loop fechado/shutdown
                log.warning("Event loop indisponível após fim de faixa (guild %s)", guild_id)

        return _after

    async def _on_finished(self, guild_id: int) -> None:
        """Chamado quando a faixa termina: avança a fila (ou encerra)."""
        try:
            if guild_id in self._stopping:
                # !stop/!leave mandaram parar: não avança e consome a supressão
                self._stopping.discard(guild_id)
                return

            guild = self.bot.get_guild(guild_id)
            vc = guild.voice_client if guild else None
            if vc is None or not vc.is_connected():
                log.info("Yuna desconectada inesperadamente na guild %s", guild_id)
                self._cleanup(guild_id)
                return

            lock = self._locks.setdefault(guild_id, asyncio.Lock())
            async with lock:
                await self._advance_locked(vc, guild_id)
        except Exception:
            log.exception("Erro inesperado ao avançar a fila da guild %s", guild_id)
            await self._send(guild_id, messages.error_embed(messages.GENERIC_ERROR))

    async def _advance_locked(self, vc: discord.VoiceClient, guild_id: int) -> None:
        """Toca o próximo item da fila. Assume que o lock da guild está no ar."""
        queue = self._queue(guild_id)
        song: Optional[Song] = None
        stream_url: Optional[str] = None

        # Pula falhas de resolução até tocar algo ou terminar a fila
        while song is None:
            candidate = queue.next()
            if candidate is None:
                break
            try:
                stream_url = await ytdl.resolve_stream(candidate)
                song = candidate
            except ytdl.BlockedError:
                log.warning("YouTube bloqueou a memória %s", candidate.webpage_url)
                await self._send(guild_id, messages.error_embed(messages.YOUTUBE_BLOCKED))
            except ytdl.SourceError:
                log.warning("Memória inacessível: %s", candidate.webpage_url)
                await self._send(guild_id, messages.error_embed(messages.INVALID_URL))

        if song is None:
            queue.set_current(None)
            if guild_id not in self._stopping:
                await self._send(guild_id, messages.info_embed(messages.QUEUE_EMPTY))
            else:
                self._stopping.discard(guild_id)
            return

        queue.set_current(song)
        executable = find_ffmpeg()
        if executable is None:
            log.error("FFmpeg não encontrado nem no PATH nem em WinGet/Gyan — impossível tocar")
            queue.forget_current()  # não trava a fila com uma música quebrada
            await self._send(guild_id, messages.error_embed(messages.FFMPEG_MISSING))
            return

        # Spawn do FFmpeg FORA do event loop: no Windows, o Popen do
        # ffmpeg.exe (carregamento + Defender) pode travar o loop por
        # ~0.5–1.5s — congestionando gateway, comandos e voz (a "lagada"
        # no início de cada música). O read() do áudio já é em thread
        # própria do discord.py; aqui só a CONSTRUÇÃO sai do loop.
        def _build_source() -> discord.PCMVolumeTransformer:
            return discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(stream_url, executable=executable, **FFMPEG_OPTIONS),
                volume=self._volume(guild_id),
            )

        loop = asyncio.get_running_loop()
        try:
            source = await loop.run_in_executor(None, _build_source)
        except Exception:
            log.exception("FFmpeg falhou ao iniciar a memória '%s'", song.title)
            queue.forget_current()  # não trava a fila com uma música quebrada
            await self._send(guild_id, messages.error_embed(messages.INVALID_URL))
            return

        try:
            vc.play(source, after=self._make_after(guild_id))
        except Exception:
            log.exception("vc.play falhou para a memória '%s'", song.title)
            queue.forget_current()  # não trava a fila com uma música quebrada
            await self._send(guild_id, messages.error_embed(messages.INVALID_URL))
            return

        log.info("Tocando '%s' na guild %s", song.title, guild_id)
        await self._send(guild_id, messages.now_playing_embed(song))
        asyncio.create_task(self._dave_diag(guild_id))

    async def _dave_diag(self, guild_id: int) -> None:
        """Diagnóstico da sessão DAVE/E2EE 6s após o play (apoio ao suporte).

        Loga em DEBUG: silencioso no dia a dia (LOG_LEVEL=INFO), à mão
        quando LOG_LEVEL=DEBUG para depurar futuras dores de voz.
        """
        try:
            await asyncio.sleep(6)
            guild = self.bot.get_guild(guild_id)
            vc = guild.voice_client if guild else None
            if vc is None or not vc.is_connected():
                return
            state = getattr(vc, "_connection", None)
            session = getattr(state, "dave_session", None)
            log.debug(
                "DAVE diag [%s]: proto_version=%r has_session=%r downgraded=%r pending=%r",
                guild_id,
                getattr(state, "dave_protocol_version", None),
                session is not None,
                getattr(state, "dave_downgraded", None),
                getattr(state, "dave_pending_transitions", None),
            )
            if session is not None:
                for name in ("status", "can_encrypt", "ready"):
                    if hasattr(session, name):
                        try:
                            log.debug(
                                "DAVE diag [%s]: session.%s=%r", guild_id, name, getattr(session, name)
                            )
                        except Exception:
                            pass
        except Exception:
            log.exception("Falha no DAVE diag da guild %s", guild_id)

    async def _start_if_idle(self, ctx: commands.Context) -> None:
        """Dá o play de partida SE nada estiver tocando na guild."""
        vc: Optional[discord.VoiceClient] = ctx.guild.voice_client
        if vc is None or not vc.is_connected():
            return
        queue = self._queue(ctx.guild.id)
        if queue.current is not None or vc.is_playing() or vc.is_paused():
            return  # algo já a toca

        lock = self._locks.setdefault(ctx.guild.id, asyncio.Lock())
        async with lock:
            # Re-checagem dentro do lock: outra coroutine pode ter começado
            queue = self._queue(ctx.guild.id)
            if queue.current is not None or vc.is_playing() or vc.is_paused():
                return
            await self._advance_locked(vc, ctx.guild.id)

    # ═════════════════════════════ !play ════════════════════════════
    @commands.command(name="play", aliases=["p"], help="Toca um vídeo, playlist ou busca.")
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        """!play <url ou busca> — a porta de entrada das memórias."""
        self._remember_channel(ctx)
        channel = self._author_voice(ctx)
        if channel is None:
            await ctx.send(embed=messages.error_embed(messages.NOT_IN_VOICE))
            return

        async with ctx.typing():
            try:
                songs: List[Song] = await ytdl.search(query, requester=ctx.author.display_name)
            except ytdl.BlockedError:
                await ctx.send(embed=messages.error_embed(messages.YOUTUBE_BLOCKED))
                return
            except ytdl.SourceError:
                await ctx.send(embed=messages.error_embed(messages.INVALID_URL))
                return
            except Exception:
                log.exception("Erro inesperado em !play (guild %s)", ctx.guild.id)
                await ctx.send(embed=messages.error_embed(messages.INVALID_URL))
                return

        if not songs:
            await ctx.send(embed=messages.error_embed(messages.INVALID_URL))
            return

        vc = await self._ensure_voice(ctx)
        if vc is None:
            await ctx.send(embed=messages.error_embed(messages.NOT_IN_VOICE))
            return

        queue = self._queue(ctx.guild.id)
        added = queue.add_multiple(songs)
        if added < len(songs):
            log.warning("Fila cheia na guild %s: %d adicionada(s) de %d", ctx.guild.id, added, len(songs))

        busy = vc.is_playing() or vc.is_paused()
        if len(songs) > 1:
            await ctx.send(embed=messages.playlist_added_embed(added, first=songs[0]))
        elif busy:
            await ctx.send(embed=messages.queued_embed(songs[0], len(queue.list())))
        # Se nada estava tocando, não manda "guardada": o embed de "tocando agora" basta.

        await self._start_if_idle(ctx)

    # ══════════════════ !pause / !resume / !skip ════════════════════
    @commands.command(name="pause", help="Pausa a memória atual.")
    async def pause(self, ctx: commands.Context) -> None:
        self._remember_channel(ctx)
        vc: Optional[discord.VoiceClient] = ctx.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await ctx.send(embed=messages.info_embed(messages.PAUSED))
        elif vc and vc.is_paused():
            await ctx.send(embed=messages.info_embed(messages.ALREADY_PAUSED))
        else:
            await ctx.send(embed=messages.error_embed(messages.NOTHING_PLAYING))

    @commands.command(name="resume", aliases=["unpause"], help="Retoma a memória pausada.")
    async def resume(self, ctx: commands.Context) -> None:
        self._remember_channel(ctx)
        vc: Optional[discord.VoiceClient] = ctx.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await ctx.send(embed=messages.info_embed(messages.RESUMED))
        elif vc and vc.is_playing():
            await ctx.send(embed=messages.info_embed(messages.ALREADY_RESUMED))
        else:
            await ctx.send(embed=messages.error_embed(messages.NOTHING_PLAYING))

    @commands.command(name="skip", aliases=["s", "pular"], help="Pula para a próxima memória.")
    async def skip(self, ctx: commands.Context) -> None:
        self._remember_channel(ctx)
        vc: Optional[discord.VoiceClient] = ctx.guild.voice_client
        queue = self._queue(ctx.guild.id)
        if not (vc and (vc.is_playing() or vc.is_paused())) or queue.current is None:
            await ctx.send(embed=messages.error_embed(messages.NOTHING_PLAYING))
            return
        queue.forget_current()  # tutorial: skip burla o loop e NÃO reenfileira
        await ctx.send(embed=messages.info_embed(messages.SKIPPED))
        vc.stop()  # o callback `after` dá sequência à fila

    # ═══════════════════ !stop / !leave ═════════════════════════════
    @commands.command(name="stop", help="Encerra a sessão e limpa a fila.")
    async def stop(self, ctx: commands.Context) -> None:
        self._remember_channel(ctx)
        vc: Optional[discord.VoiceClient] = ctx.guild.voice_client
        queue = self._queue(ctx.guild.id)
        queue.clear()
        queue.forget_current()
        self._stopping.add(ctx.guild.id)  # o callback `after` consome este flag
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        else:
            self._stopping.discard(ctx.guild.id)
        await ctx.send(embed=messages.info_embed(messages.STOPPED))

    @commands.command(name="leave", aliases=["quit", "sair"], help="Yuna sai do canal de voz.")
    async def leave(self, ctx: commands.Context) -> None:
        self._remember_channel(ctx)
        vc: Optional[discord.VoiceClient] = ctx.guild.voice_client
        queue = self._queue(ctx.guild.id)
        queue.clear()
        queue.forget_current()
        self._stopping.add(ctx.guild.id)
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()  # consome a supressão via callback `after`
        await ctx.send(embed=messages.info_embed(messages.STOPPED))
        try:
            if vc:
                await vc.disconnect(force=True)
        except (asyncio.TimeoutError, discord.ClientException) as exc:
            log.warning("Falha ao desconectar na guild %s: %r", ctx.guild.id, exc)
        finally:
            self._cleanup(ctx.guild.id)

    # ═══════════════ !queue / !nowplaying / !clear ══════════════════
    @commands.command(name="queue", aliases=["q", "fila"], help="Mostra a fila (10 por página).")
    async def queue_list(self, ctx: commands.Context, page: Optional[int] = None) -> None:
        self._remember_channel(ctx)
        queue = self._queue(ctx.guild.id)
        current = queue.current
        incoming = queue.list()
        if current is None and not incoming:
            await ctx.send(embed=messages.info_embed(messages.EMPTY_QUEUE))
            return
        await ctx.send(embed=messages.queue_embed(current, incoming, page if page else 1))

    @commands.command(
        name="nowplaying",
        aliases=["np", "tocando"],
        help="Mostra a memória que está tocando agora.",
    )
    async def nowplaying(self, ctx: commands.Context) -> None:
        self._remember_channel(ctx)
        queue = self._queue(ctx.guild.id)
        current = queue.current
        if current is None:
            await ctx.send(embed=messages.error_embed(messages.NOTHING_PLAYING))
            return
        await ctx.send(embed=messages.now_playing_embed(current))

    @commands.command(name="clear", aliases=["limpar"], help="Limpa a fila (a atual continua).")
    async def clear(self, ctx: commands.Context) -> None:
        self._remember_channel(ctx)
        queue = self._queue(ctx.guild.id)
        queue.clear()
        await ctx.send(embed=messages.info_embed(messages.QUEUE_CLEARED))

    # ═══════════════════ !volume / loops ════════════════════════════
    @commands.command(name="volume", aliases=["vol"], help="Volume de 0 a 200.")
    async def volume(self, ctx: commands.Context, level: int) -> None:
        self._remember_channel(ctx)
        if level < 0 or level > 200:
            await ctx.send(embed=messages.error_embed(messages.VOLUME_HINT))
            return
        self._volumes[ctx.guild.id] = level / 100
        vc: Optional[discord.VoiceClient] = ctx.guild.voice_client
        if vc and vc.is_playing() and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = level / 100  # aplica já na memória atual
        await ctx.send(
            embed=messages.info_embed(messages.VOLUME_SET.format(pct=level), color=messages.CYAN)
        )

    @commands.command(name="loop", help="Repete a memória atual (liga/desliga).")
    async def loop(self, ctx: commands.Context) -> None:
        self._remember_channel(ctx)
        queue = self._queue(ctx.guild.id)
        queue.loop_song = not queue.loop_song
        text = messages.LOOP_ON if queue.loop_song else messages.LOOP_OFF
        await ctx.send(embed=messages.info_embed(text, color=messages.CYAN))

    @commands.command(name="loopqueue", help="Repete a fila inteira (liga/desliga).")
    async def loopqueue(self, ctx: commands.Context) -> None:
        self._remember_channel(ctx)
        queue = self._queue(ctx.guild.id)
        queue.loop_queue = not queue.loop_queue
        text = messages.LOOP_QUEUE_ON if queue.loop_queue else messages.LOOP_QUEUE_OFF
        await ctx.send(embed=messages.info_embed(text, color=messages.CYAN))

    # ═════════════════════════════ !help ════════════════════════════
    @commands.command(name="help", aliases=["ajuda"], help="Mostra os comandos da Yuna.")
    async def help_command(self, ctx: commands.Context) -> None:
        await ctx.send(embed=messages.help_embed())

    # ════════════════════ Eventos de voz ════════════════════════════
    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        """Detecta desconexão inesperada da própria Yuna (kick/move/admin)."""
        if member.id != self.bot.user.id or before.channel is None:
            return
        if after.channel is not None:  # continua em algum canal (move normal)
            return
        log.info("Yuna deixou '%s' na guild %s — limpando estado", before.channel.name, member.guild.id)
        self._cleanup(member.guild.id)


async def setup(bot: commands.Bot) -> None:
    """Ponto de entrada usado por `bot.load_extension("cogs.music")`."""
    await bot.add_cog(MusicCog(bot))
