# 🌸 Yuna — Bot de Música do Discord

> *"Yuna está aqui. Qual memória vamos cantar hoje?"*

**Yuna** é um bot de música para Discord feito como homenagem a **Yuna**, a
cantora virtual de *Sword Art Online: The Movie — Ordinal Scale* 💗. Como a
Yuna do filme, este bot canta para os jogadores: toca vídeos e playlists do
YouTube, guarda memórias na fila, repete as favoritas e ajusta o volume da
canção — tudo com mensagens temáticas e visuais rosa, lilás e ciano.

```
🎵 !play  🎶 ... As memórias estão prontas para serem cantadas.
```

---

## 📁 Estrutura do projeto

```
yuna/
├── .dockerignore         # segredos/caches fora da imagem Docker
├── .env.example          # template do token (copie para .env)
├── .gitignore            # ignora .env, cookies.txt, __pycache__, venv...
├── Dockerfile            # (opcional) imagem da Yuna com FFmpeg embutido
├── requirements.txt      # dependências
├── cookies.txt.example   # como gerar os cookies do YouTube
├── main.py               # entrada: .env, logging, intents, cog de música
├── cogs/
│   ├── __init__.py
│   └── music.py          # comandos + motor de reprodução (fila por servidor)
└── utils/
    ├── __init__.py
    ├── messages.py       # personalidade, cores e embeds da Yuna
    ├── queue.py          # Song + MusicQueue (loops de música e de fila)
    └── ytdl.py           # extração yt-dlp (anti-bloqueio, playlists flat)
```

---

## ✅ Pré-requisitos

| Requisito | Versão       | Obrigatório? |
|-----------|--------------|--------------|
| Python    | **3.11+** (testado até 3.15) | Sim |
| FFmpeg    | qualquer estável, **no PATH do sistema** | Sim |
| Discord bot (token) | — | Sim |
| Node.js   | —            | **Opcional** (não é usado pelo bot; só relevante para alguns provedores de PO Token alternativos) |
| Docker    | —            | **Opcional** (para o PO Token via bgutil) |
| Conta Google/YouTube | qualquer | Recomendado (para cookies) |

Dependências Python (instaladas pelo `requirements.txt`):

- **discord.py[voice]** (≥ 2.4) — inclui **davey** (protocolo DAVE/E2EE, exigido pelo Discord para voz) e **PyNaCl**
- **yt-dlp** (mantenha sempre atualizado: `pip install -U yt-dlp`)
- **python-dotenv**

---

## 🛠️ 1. Instalação do FFmpeg (por sistema operacional)

O FFmpeg é obrigatório — o áudio do YouTube chega por ele. Ele deve ficar no
**PATH do sistema** para que `FFmpegPCMAudio` encontre o executável.

### Windows

**Opção A — winget (PowerShell):**
```powershell
winget install --id Gyan.FFmpeg
```
Feche e reabra o terminal. Teste com `ffmpeg -version`.

**Opção B — Chocolatey:**
```powershell
choco install ffmpeg
```

**Opção C — manual:** baixe em <https://www.gyan.dev/ffmpeg/builds/>
(`ffmpeg-release-essentials.zip`), extraia, e adicione a pasta `bin` ao
PATH: *Configurações → Sistema → Sobre → Configurações avançadas do
sistema → Variáveis de Ambiente → Path → Editar → Novo*.

### macOS

```bash
brew install ffmpeg
```
(sem Homebrew: `https://www.osxexperts.net/` ou instale o Homebrew primeiro)

### Linux

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install -y ffmpeg

# Fedora
sudo dnf install -y ffmpeg

# Arch
sudo pacman -S ffmpeg
```

Verificação universal:
```bash
ffmpeg -version
```

---

## 🤖 2. Criando o bot no Discord Developer Portal (passo a passo)

1. Acesse <https://discord.com/developers/applications> e clique
   **New Application** (nome: `Yuna`).
2. Aba **Bot** → botão **Reset Token** → copie o token
   (ele vai para o `.env` — **nunca compartilhe**).
3. Ainda na aba **Bot** → seção **Privileged Gateway Intents**:
   ligue **✅ MESSAGE CONTENT INTENT** (essencial — sem ele o bot não vê
   comandos; os demais intents já são não-privilegiados).
4. Aba **OAuth2 → URL Generator**:
   - Scopes: `bot` (+ `applications.commands` se um dia usar slash commands);
   - **Bot Permissions**: marque
     **Connect**, **Speak**, **Send Messages**, **Embed Links**
     (a permissão calculada equivalente é `3167160`);
5. Abra a URL gerada, escolha o servidor, autorize.
6. No seu servidor, crie um arquivo `.env` (passo abaixo) e rode o bot
   (`python main.py`). A Yuna aparecerá com presença "Ouvindo !play ...".

Env inteiro do bot:

```bash
# Windows
copy .env.example .env
# Linux / macOS
cp .env.example .env
```
```env
DISCORD_TOKEN=cole_o_token_aqui
LOG_LEVEL=INFO          # DEBUG | INFO | WARNING | ERROR
# YUNA_COOKIES_FILE=cookies.txt   (opcional)
```

---

## 🍪 3. Exportando o cookies.txt (anti-bloqueio do YouTube)

O YouTube bloqueia IPs de servidores/nuvens com *"Sign in to confirm you're
not a bot"*. Cookies de uma conta logada resolvem a maioria dos casos, em
formato **Netscape**:

1. Instale a extensão:
   - **Chrome / Edge / Brave:** "Get cookies.txt LOCALLY"
   - **Firefox:** "cookies.txt"
2. Abra <https://www.youtube.com> **logado** (uma conta dedicada só para o
   bot é mais segura que a principal).
3. Clique na extensão → **Export → Netscape** → salve como
   `cookies.txt` **na raiz do projeto** (mesma pasta do `main.py`).
4. Reinicie o bot. Se quiser outro nome/caminho: `YUNA_COOKIES_FILE` no `.env`.

Observações:
- O bot **não crasha** sem o cookies.txt — ele só avisa no console.
- **Renove o arquivo ~1x por semana** ou ao surgir erro de verificação de bot.
- Se o arquivo for commitado por engano, **delete-o e troque os cookies**
  (o `.gitignore` já o bloqueia).

---

## 🧪 4. PO Token com bgutil-ytdlp-pot-provider (recomendado)

Desde 2024/2025, alguns downloads sem **PO Token** são impedidos ou recebem
áudio de baixa qualidade (`Sign in to confirm you're not a bot` também aparece
nesse caso). O plugin oficial mais usado é o
[bgutil-ytdlp-pot-provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider):

**1. Suba o provedor (Docker):**
```bash
docker run --name bgutil-provider -d --init -p 127.0.0.1:4416:4416 brainicism/bgutil-ytdlp-pot-provider
```

**2. Instale o plugin do yt-dlp (no mesmo ambiente Python do bot):**
```bash
pip install -U bgutil-ytdlp-pot-provider
```

**3. Reinicie a Yuna.** O plugin detecta o provedor em `127.0.0.1:4416`
automaticamente.

Para acompanhar o provedor manualmente: `docker logs -f bgutil-provider`
(mostra requisições servidas). Para desligar:
`docker stop bgutil-provider && docker rm bgutil-provider`.

> ⚠️ **Importante sobre bloqueios:** NENHUM método garante 100% de acesso ao
> YouTube — o bloqueio muda constantemente. Estratégia recomendada:
> cookies.txt os mais recentes possíveis + PO Token (bgutil) + `yt-dlp`
> atualizado (`pip install -U yt-dlp`). Quando algo falhar, a mensagem da
> Yuna indicará "O YouTube está resistindo às minhas canções...".

---

## 🎵 5. Comandos disponíveis

| Comando | Aliases | Descrição |
|---------|---------|-----------|
| `!play <url_ou_busca>` | `p` | Toca vídeo único, **playlist inteira** ou resultado da busca (`ytsearch`). Sem canal de voz? Conecta sozinha. |
| `!pause` | — | Pausa (guarda) a memória atual. |
| `!resume` | `unpause` | Retoma a melodia. |
| `!skip` | `s`, `pular` | Pula a memória atual (burla loops; não reenfileira). |
| `!stop` | — | Encerra a sessão, esvazia a fila (a Yuna continua conectada). |
| `!leave` | `quit`, `sair` | Yuna se desconecta do canal de voz. |
| `!queue [página]` | `q`, `fila` | Mostra a fila paginada (10 itens/página) com a atual no topo. |
| `!nowplaying` | `np`, `tocando` | Embed com título, duração, thumbnail e quem pediu. |
| `!clear` | `limpar` | Limpa a fila de espera (a atual continua até terminar). |
| `!volume <0-200>` | `vol` | Ajusta o volume via `PCMVolumeTransformer` (default 100). |
| `!loop` | — | Liga/desliga loop da memória atual. |
| `!loopqueue` | — | Liga/desliga loop da fila inteira. |
| `!help` | `ajuda` | Resumo dos comandos no estilo da Yuna. |

Detalhes de comportamento:
- `!play youtube.com/watch?v=X&list=Y` enfileira a **playlist inteira** (a
  Yuna usa `noplaylist: False` por opção de projeto). Para tocar só o vídeo,
  use a URL sem `&list=`.
- `!skip` **sempre** deixa a memória atual para trás — mesmo com `!loop` ou
  `!loopqueue` ligados.
- A fila, o volume e os loops são **por servidor** — independentes entre guilds.

---

## 🚀 6. Como rodar

```bash
# 1. vá até a pasta do projeto
cd yuna

# 2. (recomendado) ambiente virtual
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux / macOS:
source venv/bin/activate

# 3. dependências
pip install -r requirements.txt

# 4. .env com o DISCORD_TOKEN (veja seção 2)

# 5. cole o cookies.txt na raiz (veja seção 3)

# 6. ligue a Yuna!
python main.py
```

No console devem aparecer:
```
INFO yuna.main: Log em nível INFO
INFO yuna.ytdl: (aviso, só se faltar cookies.txt)
INFO yuna.main: Yuna despertou. As memórias... Servidor(es) conectado(s): 1
INFO yuna.music: Extensão 'cogs.music' carregada
```

### Atalho na Área de Trabalho (comodidade)

O arquivo **`yuna.bat`** inicia a Yuna usando o venv já instalado — **sem
reinstalar nada nunca** (as dependências vivem no venv de forma permanente).
Um atalho "Yuna" (ícone de coração rosa, `yuna.ico`) fica na Área de Trabalho
apontando para o `.bat` — duplo clique liga o bot, fechar a janela encerra.
Não rode o atalho **e** o `python main.py` ao mesmo tempo (duas sessões
disputariam o mesmo login do Discord).

### Docker (opcional)

Há instruções acima para o container auxiliar de PO Token. Para a própria Yuna
em container:

```bash
# build
docker build -t yuna .

# run (token por ambiente, cookies por volume, ambos à parte da imagem)
docker run -d --name yuna-bot --restart unless-stopped \
  -e DISCORD_TOKEN=seu_token \
  -e LOG_LEVEL=INFO \
  -v "$(pwd)/cookies.txt:/app/cookies.txt:ro" \
  yuna

# logs
docker logs -f yuna-bot
```

Combine os dois: a Yuna no build acima + o provedor de PO Token do item 4 na
mesma rede Docker (se usar `docker compose`/network custom, aponte o plugin
para o hostname do provider com as variáveis do bgutil).

---

## 🩹 7. Troubleshooting (erros comuns e soluções)

| Sintoma | Causa provável | Solução |
|---------|----------------|---------|
| `PrivilegedIntentsRequired` ao subir | Message Content Intent desligado | Developer Portal → Bot → ligue **MESSAGE CONTENT INTENT** |
| `ffprobe/ffmpeg not found` ou `ffmpeg` | FFmpeg ausente ou fora do PATH | Seção 1 — instale e reabra o terminal |
| *"Sign in to confirm you're not a bot"* | IP marcado como bot | Renove `cookies.txt`; instale o PO Token (bgutil); `pip install -U yt-dlp` |
| Áudio não toca / *"Algo estranho aconteceu"* + console: `RuntimeError('davey library needed in order to use voice')` | Pacote `davey` ausente (protocolo DAVE/E2EE do Discord, obrigatório p/ voz desde 2025) | `pip install "discord.py[voice]"` (requirements.txt já cobre com o extra `[voice]`) |
| Bot conecta mas não toca / áudio mudo | Faixa bloqueada ou volume 0 | Veja o console (nível `DEBUG`); teste `!volume 100` |
| **Bot mostra anel verde (falando) mas NINGUÉM ouve — sem nenhum erro no log** | Bug do `discord.py 2.7.1` com o protocolo DAVE/E2EE: a lib nunca entrega as transições MLS à sessão davey (`session.ready` fica `False` para sempre), então os frames saem sem a camada E2EE e os clientes descartam tudo | Fix incluso: `utils/dave_fix.py`, aplicado no boot (procure no log `DAVE fix aplicado` + `execute_transition(...) (ready=True can_encrypt=True)`). Removível quando uma versão nova do discord.py corrigir; a depuração usou `LOG_LEVEL=DEBUG` e o diag `DAVE diag:` no `yuna.log` |
| `!play` com playlist enfileira menos vídeos | Entradas deletadas/privadas | Normal — a Yuna pula entradas inválidas e avisa |
| Bot fica mudo ao ser movido de canal | Estado de voz divergente | Use `!leave` + `!play` novamente (o estado é reconstruído) |
| Erro `400 Client Error` ao enviar mensagem | Falta de permissão no canal | Conceda **Send Messages** e **Embed Links** |
| Token inválido (`LoginFailure`) | Token errado/recriado | Bot → Reset Token → cole no `.env` |
| Áudio param em jogos longos? *não há* — mas, se stream cair | Reconexão FFmpeg falhou | Os flags `-reconnect` já mitigam; teste de novo `!skip` |

Para depurar mais profundo: `.env` → `LOG_LEVEL=DEBUG`.

---

## 🎨 8. Personalidade e créditos

| Botão | Cor | Uso |
|-------|-----|-----|
| 🩷 Rosa | `#FF9EC4` | padrão — "tocando agora", guardados, geral |
| 💜 Lilás | `#C8A2FF` | erros e fila |
| 💙 Ciano | `#9EE7FF` | ajustes técnicos (volume/loops) |

Mensagens e cores          → `utils/messages.py`
Motor de fila (MusicQueue) → `utils/queue.py`
Extração yt-dlp            → `utils/ytdl.py`
Comandos e voz             → `cogs/music.py`

*Yuna, de SAO, é a cantora IA que dava voz às memórias dos jogadores de
Ordinal Scale — "I will sing for you". Este bot é um humilde cover dessa
canção. 💗*

---

## 📜 Licença / Aviso

Projeto educacional. Respeite os termos de serviço do YouTube e do Discord.
Use contas e cookies com consciência.
