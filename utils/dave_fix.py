"""Workaround (monkey-patch) para o bug de silêncio do discord.py 2.7.1 + davey 0.2.0.

O bug
-----
Em `VoiceConnectionState._execute_transition` (voice_state.py), o discord.py
processa o opcode 22 (DAVE_EXECUTE_TRANSITION) apenas mexendo em seu mapa
interno de transações pendentes — ele NUNCA chama os métodos
`DaveSession.prepare_transition()` / `DaveSession.execute_transition()` da
biblioteca davey, que são os responsáveis por trocar a chave de rádio e
energar a sessão (`ready=True`, `can_encrypt=True`).

Consequência: a sessão davey fica "active" mas "not ready" para sempre, o
`VoiceClient._get_voice_packet` (voice_client.py:385) envia os frames de
áudio SEM a camada E2EE do MLS, e os clientes Discord comuns (que exigem
ciphertext válido) descartam tudo — o bot aparece falando (anel verde,
speaking=1) mas ninguém ouve nada, sem nenhum erro no log.

O fix
-----
Após o fluxo original, chamar na sessão davey:
  1. `prepare_transition(transition_id, protocol_version)` — deve ocorrer
     depois do `process_welcome`/`process_commit` (o que já aconteceu, pois
     o opcode 22 chega após o MLS welcome ter sido registrado);
  2. `execute_transition(transition_id)` — aplica a nova chave.

Referência do ciclo em davey:
  https://github.com/Snazzah/davey/blob/master/docs/USAGE.md
(process_welcome → prepare_transition → execute_transition)

Observação de auditoria: sem `process_welcome` prévio, `execute_transition`
retorna True mas NÃO energiza a sessão (ready continua False); com o
welcome aceito, a troca de chave deve acontecer. O plug continua seguro
em qualquer caso pois quem decide é o estado interno da sessão davey.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine

log = logging.getLogger("yuna.dave_fix")

_applied = False


def apply_dave_patch() -> bool:
    """Aplica o workaround uma única vez. Retorna True se foi aplicado.

    Idempotente e sem risco: se o davey não estiver instalado (voz de
    texto apenas) ou se uma versão futura do discord.py já corrigir o
    fluxo, o patch simplesmente não estraga nada — as chamadas extras na
    sessão davey são exercidas dentro de try/except e o comportamento do
    restante do voice client permanece intacto.
    """
    global _applied
    if _applied:
        return False
    _applied = True

    try:
        from discord.voice_state import VoiceConnectionState
    except ImportError:
        log.debug("DAVE fix ignorado: discord.voice_state indisponível.")
        return False

    if getattr(VoiceConnectionState, "_yuna_dave_patched", False):
        return False  # já patchado

    original: Callable[..., Coroutine[Any, Any, None]] = (
        VoiceConnectionState._execute_transition
    )

    async def _patched_execute_transition(self: Any, transition_id: int) -> None:
        # A versão alvo fica no mapa de pendências; o original faz pop dela.
        protocol_version = self.dave_pending_transitions.get(
            transition_id, self.dave_protocol_version
        )
        # Fluxo original: pop do mapa, estado de downgrade/upgrade, logs.
        await original(self, transition_id)

        session = getattr(self, "dave_session", None)
        if session is None:
            return

        try:
            session.prepare_transition(transition_id, protocol_version)
        except Exception:
            log.exception(
                "DAVE fix: prepare_transition(%d, %s) falhou",
                transition_id,
                protocol_version,
            )
            return

        try:
            executed = session.execute_transition(transition_id)
            log.debug(
                "DAVE fix: execute_transition(%d) -> %r (ready=%r can_encrypt=%r)",
                transition_id,
                executed,
                getattr(session, "ready", None),
                getattr(session, "can_encrypt", None),
            )
        except Exception:
            log.exception("DAVE fix: execute_transition(%d) falhou", transition_id)

    VoiceConnectionState._execute_transition = _patched_execute_transition  # type: ignore[assignment]
    VoiceConnectionState._yuna_dave_patched = True  # type: ignore[attr-defined]
    log.info("DAVE fix aplicado: transições serão entregues à sessão davey.")
    return True
