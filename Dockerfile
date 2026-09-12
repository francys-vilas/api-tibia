# =============================================================================
# Imagem da API do Char Bazaar
# =============================================================================
# Fica na raiz, e nao em api/, porque o contexto de build precisa ser a raiz:
# a imagem copia o tibia_bazaar_scraper.py, que mora aqui. Na raiz, o Coolify
# acha o Dockerfile com os campos no default, sem Base Directory nem
# Dockerfile Location customizados.
#
#   docker build -t tibia-bazaar-api .
# =============================================================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# As dependencias entram antes do codigo pra aproveitar o cache de camada:
# mexer no .py nao refaz o pip install.
COPY requirements.txt ./requirements.txt
COPY api/requirements.txt ./api/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r api/requirements.txt

COPY tibia_bazaar_scraper.py tibiapy_fixes.py ./
COPY api/ ./api/

# Nao roda como root.
RUN useradd --create-home --uid 10001 bazaar && chown -R bazaar:bazaar /app
USER bazaar

EXPOSE 8000

# O /health nao toca no tibia.com, entao pode ser chamado de minuto em minuto.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
