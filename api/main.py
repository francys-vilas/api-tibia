#!/usr/bin/env python3
"""
API do Tibia Char Bazaar
=========================
Expoe o scraper da raiz do repo como API HTTP, pra ser consumida pelo n8n
(ou por qualquer outra coisa) sem precisar de Python do outro lado.

Nao tem autenticacao: a ideia e rodar no Coolify sem dominio publico, so na
rede interna do Docker, onde o n8n chama http://<servico>:8000. Se um dia
precisar expor pra fora, ponha a autenticacao no proxy do Coolify ou coloque
uma checagem de header aqui.

Cache
-----
O ponto principal da API e nao raspar o tibia.com a cada chamada do n8n.
Cada combinacao de filtros vira uma chave de cache com TTL (CACHE_TTL, 5 min
por padrao) e comportamento stale-while-revalidate:

    cache fresco   -> responde na hora
    cache vencido  -> responde com o dado velho E atualiza em segundo plano
    cache vazio    -> raspa na hora (unica situacao em que a chamada demora)

Ou seja: depois da primeira chamada, o n8n nunca mais espera uma raspagem.
Chamadas simultaneas com a mesma chave nao disparam raspagens paralelas.

Rodando local:
    uvicorn api.main:app --reload      # a partir da raiz do repo
"""

import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# O scraper mora na raiz do repo, um nivel acima desta pasta.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from fastapi import FastAPI, HTTPException, Query
from tibiapy.enums import BazaarType
from tibiapy.parsers import AuctionParser, CharacterBazaarParser
from tibiapy.urls import get_auction_url, get_bazaar_url

import tibiapy_fixes
from tibia_bazaar_scraper import (
    DELAY,
    WORLD,
    build_filters,
    fetch_details,
    fetch_html,
    scrape,
    to_record,
)

# =============================================================================
# CONFIGURACAO - tudo por variavel de ambiente, pra ajustar no painel do Coolify
# =============================================================================
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))          # segundos
WORLDS_TTL = int(os.getenv("WORLDS_TTL", "86400"))      # lista de mundos muda raro
DEFAULT_WORLD = os.getenv("DEFAULT_WORLD", WORLD)
SCRAPER_DELAY = float(os.getenv("SCRAPER_DELAY", str(DELAY)))
DETAILS_MAX = int(os.getenv("DETAILS_MAX", "50"))       # teto de leiloes com details=true

log = logging.getLogger("uvicorn.error")

app = FastAPI(
    title="Tibia Char Bazaar API",
    description="Leiloes ativos do Char Bazaar do tibia.com, com cache.",
    version="1.0.0",
)


# =============================================================================
# Cache com stale-while-revalidate
# =============================================================================
@dataclass
class Entry:
    """Um resultado em cache, com o instante em que foi produzido."""
    data: Any
    monotonic: float          # pra medir idade sem sofrer com relogio do sistema
    at: datetime              # pra mostrar na resposta


_cache: dict[tuple, Entry] = {}
_locks: dict[tuple, threading.Lock] = {}
_guard = threading.Lock()     # protege os dois dicionarios acima


def _lock_for(key: tuple) -> threading.Lock:
    with _guard:
        return _locks.setdefault(key, threading.Lock())


def _store(key: tuple, data: Any) -> Entry:
    entry = Entry(data=data, monotonic=time.monotonic(), at=datetime.now(timezone.utc))
    with _guard:
        _cache[key] = entry
    return entry


def _refresh_in_background(key: tuple, produce: Callable[[], Any], lock: threading.Lock) -> None:
    """Atualiza uma chave vencida sem segurar a resposta. O lock ja veio tomado."""
    def run():
        try:
            _store(key, produce())
            log.info("cache atualizado em segundo plano: %s", key)
        except Exception as exc:  # o dado velho continua servindo
            log.warning("falhou a atualizacao de %s: %s", key, exc)
        finally:
            lock.release()

    threading.Thread(target=run, daemon=True).start()


def cached(key: tuple, produce: Callable[[], Any], ttl: int, force: bool = False) -> tuple[Any, dict]:
    """
    Devolve (dado, metadados do cache).

    force=True ignora o cache e raspa na hora - e o que o parametro
    ?refresh=true da API faz.
    """
    entry = None if force else _cache.get(key)
    now = time.monotonic()

    if entry is not None:
        age = now - entry.monotonic
        stale = age >= ttl
        if stale:
            # Vencido: responde com o velho e manda atualizar por tras, mas so
            # se ninguem ja estiver atualizando essa mesma chave.
            lock = _lock_for(key)
            if lock.acquire(blocking=False):
                _refresh_in_background(key, produce, lock)
        return entry.data, _meta(entry, age, ttl, hit=True, stale=stale)

    # Sem nada em cache: alguem tem que esperar. O lock faz com que chamadas
    # simultaneas aproveitem a mesma raspagem em vez de dispararem varias.
    lock = _lock_for(key)
    with lock:
        entry = None if force else _cache.get(key)
        if entry is None:
            inicio = time.monotonic()
            entry = _store(key, produce())
            log.info("raspagem de %s levou %.1fs", key, time.monotonic() - inicio)
    return entry.data, _meta(entry, time.monotonic() - entry.monotonic, ttl, hit=False, stale=False)


def _meta(entry: Entry, age: float, ttl: int, hit: bool, stale: bool) -> dict:
    return {
        "hit": hit,
        "stale": stale,
        "age_seconds": round(age, 1),
        "ttl_seconds": ttl,
        "fetched_at": entry.at.isoformat().replace("+00:00", "Z"),
    }


# =============================================================================
# Raspagem (funcoes sincronas - o FastAPI roda endpoints `def` num threadpool)
# =============================================================================
def _scrape_records(world: str, vocation: int, level_from: int, level_to: int,
                    limit: Optional[int], max_pages: Optional[int],
                    details: bool) -> list[dict]:
    session = requests.Session()
    auctions = scrape(
        vocation=vocation,
        world=world,
        level_from=level_from,
        level_to=level_to,
        max_pages=max_pages,
        delay=SCRAPER_DELAY,
        limit=limit,
        session=session,
    )
    if details and auctions:
        fetch_details(session, auctions, delay=SCRAPER_DELAY)
    return [to_record(a) for a in auctions]


def _scrape_worlds() -> list[str]:
    """A propria pagina do bazaar publica a lista de mundos no formulario de filtro."""
    url = get_bazaar_url(BazaarType.CURRENT, page=1, filters=build_filters(0, "", 0, 0))
    bazaar = CharacterBazaarParser.from_content(fetch_html(requests.Session(), url))
    return list(bazaar.filters.available_worlds) if bazaar.filters else []


def _scrape_auction(auction_id: int) -> Optional[dict]:
    tibiapy_fixes.apply()  # o parser de detalhe do tibia.py 6.4.0 esta defasado
    html = fetch_html(requests.Session(), get_auction_url(auction_id))
    auction = AuctionParser.from_content(html, auction_id)
    return to_record(auction) if auction is not None else None


def _guarded(produce: Callable[[], Any]) -> Callable[[], Any]:
    """Traduz erro de rede/HTTP do tibia.com em 502, em vez de 500 generico."""
    def run():
        try:
            return produce()
        except requests.RequestException as exc:
            raise HTTPException(status_code=502, detail=f"tibia.com nao respondeu: {exc}") from exc
    return run


# =============================================================================
# Endpoints
# =============================================================================
@app.get("/", summary="Indice")
def index() -> dict:
    return {
        "service": "tibia-bazaar-api",
        "docs": "/docs",
        "endpoints": ["/health", "/worlds", "/auctions", "/auctions/{auction_id}"],
        "defaults": {
            "world": DEFAULT_WORLD or "todos",
            "cache_ttl_seconds": CACHE_TTL,
            "scraper_delay_seconds": SCRAPER_DELAY,
        },
    }


@app.get("/health", summary="Healthcheck do Coolify")
def health() -> dict:
    """Nao toca no tibia.com: so diz que o processo esta de pe."""
    return {
        "status": "ok",
        "cached_keys": len(_cache),
        "time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


@app.get("/worlds", summary="Mundos que existem no bazaar")
def worlds(refresh: bool = Query(False, description="Ignora o cache e busca de novo")) -> dict:
    data, meta = cached(("worlds",), _guarded(_scrape_worlds), WORLDS_TTL, force=refresh)
    return {"count": len(data), "worlds": data, "cache": meta}


@app.get("/auctions", summary="Leiloes ativos")
def auctions(
    world: str = Query(DEFAULT_WORLD, description='Nome exato do mundo; "" = todos'),
    vocation: int = Query(0, ge=0, le=6,
                          description="0=todas 1=None 2=Druid 3=Knight 4=Paladin 5=Sorcerer 6=Monk"),
    level_from: int = Query(0, ge=0, description="0 = sem minimo"),
    level_to: int = Query(0, ge=0, description="0 = sem maximo"),
    limit: Optional[int] = Query(None, ge=0, description="Traz so os N primeiros; 0 = todos"),
    max_pages: Optional[int] = Query(None, ge=0, description="Teto de paginas; 0 = sem teto"),
    details: bool = Query(False, description="Ficha completa de cada char (1 requisicao por leilao)"),
    refresh: bool = Query(False, description="Ignora o cache e raspa na hora"),
) -> dict:
    """
    A ordenacao e por data de fim do leilao, entao `limit=10` traz os 10 que
    terminam primeiro.

    Sem `world`, sao ~2600 leiloes em mais de 100 paginas: a primeira chamada
    demora uns 2 minutos. Com cache quente, responde na hora.
    """
    # 0 significa "sem limite", mesma convencao do scraper e do workflow do n8n.
    limit = limit or None
    max_pages = max_pages or None

    if details and (limit is None or limit > DETAILS_MAX):
        raise HTTPException(
            status_code=400,
            detail=f"details=true exige limit de no maximo {DETAILS_MAX}: "
                   f"cada leilao custa uma requisicao a mais ao tibia.com.",
        )

    key = ("auctions", world, vocation, level_from, level_to, limit, max_pages, details)
    produce = _guarded(lambda: _scrape_records(
        world, vocation, level_from, level_to, limit, max_pages, details))
    data, meta = cached(key, produce, CACHE_TTL, force=refresh)

    return {
        "count": len(data),
        "filters": {
            "world": world or None,
            "vocation": vocation,
            "level_from": level_from,
            "level_to": level_to,
            "limit": limit,
            "max_pages": max_pages,
            "details": details,
        },
        "cache": meta,
        "auctions": data,
    }


@app.get("/auctions/{auction_id}", summary="Um leilao, com a ficha completa")
def auction(
    auction_id: int,
    refresh: bool = Query(False, description="Ignora o cache e busca de novo"),
) -> dict:
    data, meta = cached(("auction", auction_id), _guarded(lambda: _scrape_auction(auction_id)),
                        CACHE_TTL, force=refresh)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Leilao {auction_id} nao encontrado")
    return {"cache": meta, "auction": data}
