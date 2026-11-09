"""Fila de reprodução por servidor da Yuna.

Contém a `Song` (metadados de uma memória) e a `MusicQueue` (fila circular
com suporte a loop por música e loop da fila). Este módulo é puro — sem
dependências de Discord — para facilitar testes e reuso.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Song:
    """Uma "memória" — uma música aguardando ou tocando."""

    title: str
    # Link público da música (usado para re-resolver o stream quando expira)
    webpage_url: str
    # URL DIRETA de áudio. Em entradas de playlist com extract_flat ela vem
    # como None e é resolvida por `utils.ytdl.resolve_stream()` no momento do play.
    stream_url: Optional[str] = None
    # Duração em segundos. None = ao vivo ou desconhecido.
    duration: Optional[float] = None
    thumbnail: Optional[str] = None
    requester: str = "desconhecido"


class MusicQueue:
    """Fila FIFO com loop por música (`loop_song`) e loop da fila (`loop_queue`).

    Convenções importantes para o motor de reprodução (cogs/music.py):
      • `current` é a música em reprodução OU pausada (não é removida daqui
        automaticamente — o motor chama `forget_current()` no !skip/!stop).
      • `next()` avança respeitando os loops e já devolve a próxima a tocar.
      • `list()` devolve uma CÓPIA da lista de espera (segura para iterar).
    """

    def __init__(self, max_size: int = 0) -> None:
        self._items: deque[Song] = deque()
        self._current: Optional[Song] = None
        self.max_size = max_size  # 0 = ilimitado
        self.loop_song: bool = False
        self.loop_queue: bool = False

    # ── Propriedades ─────────────────────────────────────────────────────────
    @property
    def current(self) -> Optional[Song]:
        """Música atual (tocando/pausada), ou None."""
        return self._current

    @current.setter
    def current(self, song: Optional[Song]) -> None:
        """Define a música atual (None limpa). Usado pelo motor do player."""
        self._current = song

    def set_current(self, song: Optional[Song]) -> None:
        """Alias explícito para ajustar a música atual."""
        self._current = song

    def __len__(self) -> int:
        return len(self._items)

    # ── Operações da fila ────────────────────────────────────────────────────
    def add(self, song: Song) -> bool:
        """Adiciona uma música ao fim da fila. False se a fila estiver cheia."""
        if self.max_size and len(self._items) >= self.max_size:
            return False
        self._items.append(song)
        return True

    def add_multiple(self, songs: List[Song]) -> int:
        """Enfileira várias músicas (playlists). Devolve quantas entraram."""
        added = 0
        for song in songs:
            if self.add(song):
                added += 1
        return added

    def next(self) -> Optional[Song]:
        """Avança para a próxima memória a tocar, aplicando os loops.

        Chamado quando a música atual termina (ou é pulada — nesse caso o
        motor limpa `current` ANTES de chamar este método, burlando o loop).
        """
        cur = self._current
        if cur is None:
            # Sem música atual: apenas desenfileira se houver algo esperando.
            return self._items.popleft() if self._items else None

        # Loop por música: repete a atual (por cima do loop da fila).
        if self.loop_song:
            return cur

        self._current = None
        if self.loop_queue:
            self._items.append(cur)  # atual volta para o fim da fila
        return self._items.popleft() if self._items else None

    def forget_current(self) -> Optional[Song]:
        """Descarta a referência da música atual SEM reenfileirá-la.

        Usado por !skip (a memória "fica para trás", mesmo com loop) e !stop.
        Devolve a música descartada, se existia.
        """
        dropped = self._current
        self._current = None
        return dropped

    def clear(self) -> None:
        """Esvazia a lista de espera (a música atual NÃO é afetada)."""
        self._items.clear()

    def is_empty(self) -> bool:
        """True se não há nada na lista de espera."""
        return not self._items

    def list(self) -> List[Song]:
        """Cópia ordenada da lista de espera (para exibir / medir posições)."""
        return list(self._items)
