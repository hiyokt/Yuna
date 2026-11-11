"""Ponto de entrada do bot Yuna (SAO: Ordinal Scale).

Responsabilidades:
  • carregar variáveis do .env;
  • configurar logging com timestamp e nível (LOG_LEVEL);
  • criar o bot com as intents necessárias e carregar o cog de música;
  • encerrar limpo quando o usuário apertar Ctrl+C.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time

import discord
from discord.ext import commands
from dotenv import load_dotenv

from utils import messages, ytdl
from utils.dave_fix import apply_dave_patch
from utils.ffmpeg import ensure_deno_path

log = logging.getLogger("yuna.main")


def _configure_logging() -> None:
    """Logging no console + em arquivo (yuna.log), com nível configurável."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    if not isinstance(level, int):  # LOG_LEVEL com valor inválido → fallback
        level = logging.INFO
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%d/%m %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(level)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)
    # Arquivo persistente: permite pós mortem dos erros sem copiar o console
    file_handler = logging.FileHandler("yuna.log", encoding="utf-8", mode="a")
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)
    # Reduz o ruído das bibliotecas internas do discord.py — MAS NÃO em DEBUG,
    # caso contrário os detalhes do transporte de voz ficam invisíveis.
    if level > logging.DEBUG:
        logging.getLogger("discord").setLevel(logging.WARNING)
        logging.getLogger("discord.http").setLevel(logging.WARNING)
    log.info("Log em nível %s (console + arquivo)", logging.getLevelName(level))


# Intents necessárias: guilds, voice_states, guild_messages e message_content.
# O "Message Content Intent" TAMBÉM precisa estar ligado no Developer Portal!
intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True
intents.messages = True
intents.message_content = True


class YunaBot(commands.Bot):
    """Subclasse mínima para registrar hooks da Yuna."""

    def __init__(self) -> None:
        super().__init__(
            command_prefix="!",  # comandos com o prefixo "!", ex.: !play
            intents=intents,
            help_command=None,   # a !help é a personalizada do cog de música
            case_insensitive=True,
        )

    async def setup_hook(self) -> None:
        """Carrega extensões antes de conectar à gateway."""
        await self.load_extension("cogs.music")
        log.info("Extensão 'cogs.music' carregada")
        self.loop.create_task(self._lag_watchdog())

    @staticmethod
    async def _lag_watchdog(interval: float = 1.0, threshold: float = 0.7) -> None:
        """Mede a saúde do event loop: se ele dormir além do esperado, loga.

        A cada `interval` a task dorme `asyncio.sleep(interval)`; como o loop
        deveria acordá-la em ponto (±jitter de kHz), um atraso bem acima
        disso significa que ALGO bloqueou/estrelou o loop (GIL do yt-dlp,
        I/O síncrono, CPU carregada) — a causa raiz de "linhagens de lag".
        Loga no máx. 1 vez a cada 5s para não virar espalhafato.
        """
        last_warn = 0.0
        while True:
            started = time.perf_counter()
            await asyncio.sleep(interval)
            drift = time.perf_counter() - started - interval
            if drift > threshold and time.perf_counter() - last_warn > 5.0:
                last_warn = time.perf_counter()
                log.warning(
                    "Loop congestionado: tarefa dormindo %.2fs a mais que os %.1fs "
                    "esperados (CPU/loop bloqueados ou estrelados)",
                    drift,
                    interval,
                )

    async def on_ready(self) -> None:
        log.info("%s Servidor(es) conectado(s): %d", messages.ON_READY, len(self.guilds))
        # Presença: "Ouvindo !play ..." — como se a Yuna estivesse no palco
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="!play • uma canção de SAO 💗",
            )
        )

    async def on_command_error(self, ctx: commands.Context, error: BaseException) -> None:
        """Último socorro: erros que escaparam do tratamento dentro do cog."""
        if isinstance(error, commands.CommandNotFound):
            return  # comandos inexistente não são erros do usuário
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=messages.error_embed(messages.USAGE_HINT))
            return
        if isinstance(error, commands.BadArgument):
            await ctx.send(embed=messages.error_embed(messages.USAGE_HINT))
            return
        if isinstance(error, commands.CommandInvokeError):
            error = error.original  # unwrap para logar a causa raiz com o traceback dela
        log.error("Erro não tratado no comando (traceback completo abaixo)", exc_info=error)
        await ctx.send(embed=messages.error_embed(messages.GENERIC_ERROR))


def main() -> None:
    """Executa a Yuna: .env → logging → verificação de token → bot.run."""
    load_dotenv()
    _configure_logging()

    # Workaround do bug de silêncio (davey): deve rodar antes do bot.connect.
    apply_dave_patch()

    # Deno no PATH: o yt-dlp precisa dele para resolver o desafio "n" do
    # YouTube (sem = formatos de áudio descartados = "format not available").
    if ensure_deno_path():
        log.info("Deno disponível (runtime JS do yt-dlp para o desafio 'n' do YouTube)")
    else:
        log.warning(
            "Deno NÃO encontrado — o yt-dlp pode falhar com 'Requested format is not "
            "available'. Instale com: winget install DenoLand.Deno"
        )

    # Aviso sobre cookies acontece APÓS o logging estar configurado
    ytdl.warn_if_no_cookies()

    token = (os.getenv("DISCORD_TOKEN") or "").strip()
    if not token:
        log.error(
            "DISCORD_TOKEN não definido! Copie .env.example para .env, cole o token "
            "do Developer Portal e tente de novo."
        )
        sys.exit(1)

    bot = YunaBot()
    try:
        # log_handler=None: o discord.py NÃO deve reconfigurar nosso logging
        bot.run(token, log_handler=None)
    except KeyboardInterrupt:
        log.info("Yuna descansando... até a próxima memória. 🌸")
    except discord.LoginFailure:
        log.error("Token inválido! Recrie o token no Developer Portal (Bot → Reset Token).")
        sys.exit(1)
    except discord.errors.PrivilegedIntentsRequired:
        log.error(
            "MESSAGE CONTENT INTENT desligada no Developer Portal! "
            "Vá em: https://discord.com/developers/applications → sua aplicação → "
            "aba Bot → Privileged Gateway Intents → ligue "
            "'MESSAGE CONTENT INTENT' → Save Changes → rode novamente."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
