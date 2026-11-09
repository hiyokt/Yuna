# 🎶 Yuna — Diário do Desenvolvimento

*Resumo de tudo que foi feito para construir, depurar e publicar a Yuna,
bot de música para Discord (homenagem à Yuna de SAO: Ordinal Scale,
"I will sing for you").*

---

## 1. O que é

Um bot de música com prefixo `!`, chamado **Yuna**, que entra no canal de
voz e toca música do YouTube. Em Python 3.11+, com:

- **discord.py 2.7.1** + extras `[voice]` (que trazem **davey 0.2.0** e **PyNaCl**);
- **yt-dlp** para extração de áudio do YouTube (com anti-bloqueio);
- **FFmpeg** para decodificar o áudio;
- **python-dotenv** para o `.env`.

## 2. Estrutura final

| Arquivo | Papel |
|---------|-------|
| `main.py` | Ponto de entrada: `.env`, logging (console + `yuna.log`), intents, handlers de erro |
| `cogs/music.py` | Os 13 comandos + o motor de reprodução por servidor |
| `utils/music_queue.py` → `utils/queue.py` | `MusicQueue` — fila por guild (deque) com loop por música e loop da fila |
| `utils/ytdl.py` | Extração yt-dlp anti-bloqueio; aviso de cookies ausentes (1×, sem crashar) |
| `utils/ffmpeg.py` | Descoberta dinâmica do FFmpeg (PATH → winget Gyan) — independe do PATH do terminal |
| `utils/messages.py` | Mensagens temáticas (tons rosa `#FF9EC4`, lilás `#C8A2FF`, ciano `#9EE7FF`) |
| `utils/dave_fix.py` | **Workaround do bug de silêncio DAVE** (ver §4.2) |
| `yuna.bat` | Launcher do Windows (uso direto do `venv\Scripts\python.exe`, com guardas) |
| `yuna.ico` | Ícone: coração rosa gerado com Pillow |
| `Yuna.lnk` (Screen no Desktop) | Atalho para o `yuna.bat` — liga a Yuna com duplo clique |
| `Dockerfile`, `.dockerignore` | Rodar em container (alternativa ao atalho) |
| `cookies.txt.example` | Modelo do cookies.txt do YouTube (formato Netscape) |
| `README.md` | Manual completo: setup, cookies, PO Token, Docker, troubleshooting |

### Comandos

`!play` (URL/vídeo/playlist/`ytsearch:` e busca pelo nome) · `!pause` ·
`!resume` · `!skip` · `!stop` · `!leave` · `!queue` (paginado, 10/pág.) ·
`!nowplaying` · `!clear` · `!volume` (0–200) · `!loop` · `!loopqueue` · `!help`

## 3. Setup e correções de ambiente

1. **`discord.py` sem o extra** → `RuntimeError: davey library needed...`.
   Fixoozinho: `pip install "discord.py[voice]"`.
2. **FFmpeg ausente** → instalado via **winget** (Gyan 9.0.2). Como o PATH
   do terminal da janela do `yuna.bat` não garantia o FFmpeg, o
   `utils/ffmpeg.py` o localiza dinamicamente e o caminho é passado
   como `executable=` ao `FFmpegPCMAudio`.
3. **Cookies do YouTube (opcional)**: aviso idempotente quando
   `cookies.txt` (env `YUNA_COOKIES_FILE`) não existe — a Yuna sobe mesmo
   sem; alguns vídeos podem pedir "Sign in to confirm...".
4. **Intents**: o `PrivilegedIntentsRequired` virou mensagem amigável +
   instrução do Developer Portal (Message Content Intent precisa estar
   LIGADA lá, não só no código).
5. **Logging**: dual (console + `yuna.log`); `discord.*` só é abafado para
   WARNING quando `LOG_LEVEL` ≠ DEBUG.
6. **RMS do PCM** testado = 692 (áudio REAL em trânsito) — pipeline
   comprovado antes de olhar a voz.

## 4. A saga "som off" (o caso DAVE)

Sintoma: **bot emite (anel verde no Discord), mas ninguém no canal ouve;
os demais usuários se ouvem entre si.** Sem nenhum erro no log.

### 4.1 O rastro de depuração

- Handshake de voz saudável: mode `aead_xchacha20_poly1305_rtpsize` ✔,
  IP discovery (UDP) ✔, FFmpeg com caminho completo ✔;
- `discord.py 2.7.1` e `davey 0.2.0`: **versões mais recente — sem
  upgrade possível**;
- **Zero** falhas MLS / "not for this epoch" / exceptions no `yuna.log`;
- Opcode 24 (`DAVE_PREPARE_EPOCH`) **wireado** na lib (apanágio do bug
  análogo do nextcord #1294 descartado);
- Reports de outros ecossistemas (Discord.Net PR #1823/#1832, nextcord)
  → classe de bug "silent fail multiparty" confirmada na natureza;
- Instrumentado o cog com `_dave_diag()` (loga a sessão davey 6s após o
  play) → revelou:

  ```
  session.status     = SessionStatus.active
  session.can_encrypt = False   ← sem chave de rádio!
  session.ready       = False
  proto_version=1, downgraded=False, pending={}
  ```

### 4.2 O achado (bug da lib)

Em `VoiceConnectionState._execute_transition` (voice_state.py), o
discord.py processa o opcode 22 (DAVE_EXECUTE_TRANSITION) **apenas** em
seu mapa interno de pendências — ele **nunca** chama os métodos
`DaveSession.prepare_transition()` / `execute_transition()` da biblioteca
davey, que são os responsáveis por trocar a chave de rádio e energizar a
sessão (`ready=True`, `can_encrypt=True`).

Consequência: a sessão davey fica "active" mas "not ready" para sempre, o
`VoiceClient._get_voice_packet` (voice_client.py:385) envia os frames **sem
a camada E2EE do MLS**; os clientes discord.com comuns (que exigem
ciphertext válido) descartam tudo. Resultado: o bot aparece falando
(anel verde, speaking=1) mas **ninguém ouve nada, sem nenhum erro**.

`execute_transition` NÃO energiza a sessão sozinho sem um `process_welcome`
prévio — audição davey em si, isolado, sem rede: `ready` permanece False;
com o welcome já aceito no bot, a troca de chave acontece.

### 4.3 O fix

`utils/dave_fix.py` — monkey-patch aplicado no boot (`main.py`):
após o fluxo original, ele entrega a transição **à sessão davey**
(`prepare_transition(id, versão)` → `execute_transition(id)`) via closure.

Auditado: compilação ✔, idempotente ✔, wrap `__module__ == 'utils.dave_fix'` ✔,
fluxo exercido com boneco (`prep=[(7,1)]`→`exec=[7]`) ✔, `dave_session=None`
sem crash ✔.

**Prova final no `yuna.log`:**

```
DAVE fix: execute_transition(9) -> True (ready=True can_encrypt=True) ✓
```

E o usuário dirigiu o majestoso verbo: **"FOIIIIIII"** — som on. 🎉

## 5. Atalho no Desktop

- `yuna.bat` usa o `venv\Scripts\python.exe` **direto** (não depende do
  PATH do sistema), com guardas para venv ausente e `.env` ausente;
- `yuna.ico` ≥ gerado com Pillow (coração rosa);
- `Yuna.lnk` no Desktop → aponta para o `yuna.bat`.

## 6. Publicação no GitHub

- Repo local **git init -b main** em `C:\Users\gusta\Desktop\sla\yuna`;
- Identidade: `hiyokt` + e-mail anonimizado
  `hiyokt@users.noreply.github.com` (config local do repo);
- Autor da raiz re-marcado: `e6886f5 hiyokt <hiyokt@users.noreply.github.com>`;
- `.env` **comprovadamente** fora do commit (`git check-ignore -v .env`
  → `.gitignore:2:.env`); `yuna.log`, `venv/`, `cookies.txt`,
  `__pycache__` fora também;
- Remote `origin` = `https://github.com/hiyokt/Yuna.git`;
- Push: `main → origin/main` — **prova no servidor**: `git ls-remote`
  S-H-A `e6886f5…` idêntico ao local; branch rastreando.

## 7. Como rodar (o dia-a-dia)

```
Duplo clique no atalho "Yuna" (Desktop)
```

ou, no terminal:

```
cd C:\Users\gusta\Desktop\sla\yuna
.\yuna.bat
```

## 8. Como manter (o futuro)

- Novos recursos: edit no código → `git add -A` → `git commit -m "msg"` →
  `git push`;
- Nova versão do `discord.py` **podendo retirar o patch**: re-testar
  `!play` após `pip install -U "discord.py[voice]"`; se a lib passar a
  entregar as transições à sessão davey por conta própria, o patch
  `utils/dave_fix.py` pode ser removido (mudança de uma linha no
  `main.py`);
- Nota de log: `LOG_LEVEL=DEBUG` somo úlitima rogada; `.env`
  permanece em `INFO` para produção;
- Troca de token: `.env` → `DISCORD_TOKEN` (nunca no repo!).

---

*Yuna, de SAO, cantava as memórias dos jogadores. Este projeto é a
memória do build — agora documentada, versionada no GitHub para
nunca se perder.*

**"I will sing for you."** 💗
