# ════════════════════════════════════════════════════════════════════════════
#  Yuna — Bot de Música do Discord (SAO: Ordinal Scale)
#  Build:  docker build -t yuna .
#  Run:    docker run -d --name yuna-bot --restart unless-stopped \
#             -e DISCORD_TOKEN=seu_token \
#             -v %cd%\cookies.txt:/app/cookies.txt:ro \
#             yuna
# ════════════════════════════════════════════════════════════════════════════
FROM python:3.11-slim

# FFmpeg (obrigatório) + ca-certificates para as conexões TLS do yt-dlp
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cache de dependências: copiamos primeiro o arquivo de requisitos
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código do bot (cookies.txt e .env NÃO são copiados — vêm por volume/env,
# assim segredos ficam fora da imagem e do histórico do Docker)
COPY main.py .
COPY cogs/ cogs/
COPY utils/ utils/

# O bot roda como usuário sem privilégios
RUN useradd --create-home yuna && chown -R yuna:yuna /app
USER yuna

# Cookies (monte por volume) ficam na raiz /app; token via -e DISCORD_TOKEN
ENV LOG_LEVEL=INFO
CMD ["python", "main.py"]
