#!/usr/bin/env python3
"""
Tibia Char Bazaar Scraper
==========================
Raspa os leiloes ativos do Char Bazaar oficial (tibia.com) e devolve
os dados estruturados. Suporta os mesmos filtros da página oficial
(vocação, mundo, level, skill, etc.) e paginação automática.

O parse do HTML e feito pela biblioteca tibia.py, entao os campos vem
tipados (datas como datetime, vocacao e status como enum) e o script nao
precisa manter regex propria pra estrutura da pagina.

Os filtros padrao ficam no bloco CONFIGURACAO logo abaixo dos imports
(WORLD, VOCATION, LEVEL_FROM, ...). Edite ali pra mudar o comportamento
de uma rodada sem flag; as flags da CLI sobrescrevem esses valores.

Uso basico:
    pip install -r requirements.txt
    python tibia_bazaar_scraper.py        # usa o bloco CONFIGURACAO

Exemplos:
    # Knights (vocation=3) em Calmera
    python tibia_bazaar_scraper.py --vocation 3

    # Outro mundo
    python tibia_bazaar_scraper.py --world Antica

    # Todos os mundos (string vazia desliga o filtro)
    python tibia_bazaar_scraper.py --world ""

    # Com a ficha completa de cada personagem (1 requisicao a mais por leilao)
    python tibia_bazaar_scraper.py --limit 5 --details

    # Exporta pra JSON
    python tibia_bazaar_scraper.py --vocation 3 --json saida.json

Codigos de vocacao (AuctionVocationFilter):
    0 = todas | 1 = None | 2 = Druid | 3 = Knight | 4 = Paladin | 5 = Sorcerer | 6 = Monk

    (Obs: no Exevo Pan a numeracao e diferente. Estes sao os codigos do
     tibia.com oficial, os mesmos que o tibia.py usa.)
"""

from datetime import datetime
import argparse
import difflib
import json
import sys
import time
from pathlib import Path

import requests
from tibiapy.enums import (
    AuctionBattlEyeFilter,
    AuctionOrderBy,
    AuctionOrderDirection,
    AuctionVocationFilter,
    BazaarType,
    PvpTypeFilter,
)
from tibiapy.models import Auction, AuctionFilters, CharacterBazaar
from tibiapy.parsers import AuctionParser, CharacterBazaarParser
from tibiapy.urls import get_auction_url, get_bazaar_url

import tibiapy_fixes

# =============================================================================
# CONFIGURACAO - edite os valores daqui pra mudar os filtros padrao
# =============================================================================
# Tudo abaixo e so o DEFAULT: as flags da linha de comando continuam
# sobrescrevendo qualquer um deles numa rodada especifica.

WORLD = "Calmera"       # nome exato do mundo (case-sensitive); "" = todos
VOCATION = 0            # 0=todas 1=None 2=Druid 3=Knight 4=Paladin 5=Sorcerer 6=Monk
LEVEL_FROM = 0          # 0 = sem minimo
LEVEL_TO = 0            # 0 = sem maximo
LIMIT = None            # None = traz tudo; N = para nos N primeiros
MAX_PAGES = None        # None = sem teto de paginas
DELAY = 1.0             # pausa entre requisicoes, em segundos. NAO use 0.
DETAILS = False         # True = abre a pagina de cada leilao (1 requisicao por leilao)

# Saida
PRINT_JSON = True       # True = mostra o JSON no terminal; False = lista resumida
SAVE_JSON = True        # True = grava um arquivo .json a cada rodada
OUTPUT_DIR = "saida"    # pasta dos arquivos gerados (criada se nao existir)

# Filtros sem flag equivalente na CLI: so da pra mudar por aqui.
PVP_TYPE = None         # None = todos | 0=Open 1=Optional 2=Hardcore 3=Retro Open 4=Retro Hardcore
BATTLEYE_STATE = None   # None = todos | 1=Initially Protected 2=Protected 3=Not Protected
ORDER_COLUMN = 101      # 101 = fim do leilao (100=lance 102=level 103=inicio)
ORDER_DIRECTION = 1     # 1 = crescente (quem termina antes vem primeiro)

# =============================================================================

# Um User-Agent de navegador de verdade evita bloqueios simples.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}


def build_filters(vocation: int, world: str, level_from: int, level_to: int) -> AuctionFilters:
    """Monta o objeto de filtros do tibia.py a partir dos valores crus."""
    try:
        return AuctionFilters(
            world=world or None,
            vocation=AuctionVocationFilter(vocation) if vocation else None,
            min_level=level_from or None,
            max_level=level_to or None,
            pvp_type=PvpTypeFilter(PVP_TYPE) if PVP_TYPE is not None else None,
            battleye=AuctionBattlEyeFilter(BATTLEYE_STATE) if BATTLEYE_STATE is not None else None,
            order_by=AuctionOrderBy(ORDER_COLUMN),
            order=AuctionOrderDirection(ORDER_DIRECTION),
        )
    except ValueError as exc:
        sys.exit(f"[x] Filtro invalido: {exc}")


def fetch_html(session: requests.Session, url: str) -> str:
    """Baixa uma pagina do bazaar. Retorna o HTML cru."""
    resp = session.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def warn_unknown_world(world: str, bazaar: CharacterBazaar) -> None:
    """
    A pagina de filtros traz a lista de mundos existentes. Se o nome pedido
    nao estiver nela, o tibia.com ignora o filtro em silencio e devolve o
    bazaar inteiro - entao vale avisar, em vez de deixar o usuario achar que
    o mundo simplesmente nao tem leilao.
    """
    mundos = bazaar.filters.available_worlds if bazaar.filters else []
    if not world or not mundos or world in mundos:
        return

    aviso = f"[!] '{world}' nao esta na lista de {len(mundos)} mundos do bazaar."
    if parecidos := difflib.get_close_matches(world, mundos, n=3):
        aviso += f" Voce quis dizer: {', '.join(parecidos)}?"

    print(aviso, file=sys.stderr)
    print("[!] O filtro de mundo foi ignorado pelo tibia.com.", file=sys.stderr)


def scrape(vocation=VOCATION, world=WORLD, level_from=LEVEL_FROM,
           level_to=LEVEL_TO, max_pages=MAX_PAGES, delay=DELAY,
           limit=LIMIT, session=None) -> list[Auction]:
    """
    Raspa o bazaar inteiro (ou parte dele) com os filtros dados.

    delay = pausa em segundos entre requisicoes. NAO reduza pra 0:
            ser educado com o servidor da CipSoft evita bloqueio.
    """
    session = session or requests.Session()
    filters = build_filters(vocation, world, level_from, level_to)

    def pagina(n: int) -> CharacterBazaar:
        url = get_bazaar_url(BazaarType.CURRENT, page=n, filters=filters)
        return CharacterBazaarParser.from_content(fetch_html(session, url))

    # Primeira pagina: descobre quantas paginas existem
    bazaar = pagina(1)
    warn_unknown_world(world, bazaar)

    total = bazaar.total_pages or 1
    if max_pages:
        total = min(total, max_pages)

    print(f"[i] {bazaar.results_count or 0} leiloes no filtro; "
          f"paginas a raspar: {total}", file=sys.stderr)

    all_auctions = list(bazaar.entries)
    print(f"[i] Pagina 1/{total}: {len(all_auctions)} leiloes", file=sys.stderr)

    # Com --limit nao adianta baixar o resto: para assim que tiver o bastante.
    if limit and len(all_auctions) >= limit:
        return all_auctions[:limit]

    for page in range(2, total + 1):
        time.sleep(delay)  # <-- educacao com o servidor
        page_auctions = pagina(page).entries
        all_auctions.extend(page_auctions)
        print(f"[i] Pagina {page}/{total}: {len(page_auctions)} leiloes", file=sys.stderr)
        if limit and len(all_auctions) >= limit:
            break

    return all_auctions[:limit] if limit else all_auctions


def fetch_details(session: requests.Session, auctions: list[Auction],
                  delay: float = DELAY) -> None:
    """
    Abre a pagina de cada leilao e preenche o campo `details` no lugar.
    Custa UMA requisicao por leilao, entao so vale com --limit ou com filtro
    apertado. Leilao que falhar fica com details = None e a rodada segue.
    """
    tibiapy_fixes.apply()  # o parser de detalhe do tibia.py 6.4.0 esta defasado

    for i, auction in enumerate(auctions, start=1):
        time.sleep(delay)
        print(f"[i] Detalhe {i}/{len(auctions)}: {auction.name}", file=sys.stderr)
        try:
            html = fetch_html(session, get_auction_url(auction.auction_id))
            completo = AuctionParser.from_content(html, auction.auction_id)
        except Exception as exc:  # um leilao quebrado nao derruba a rodada
            print(f"[!] Falhou o detalhe de {auction.name}: {exc}", file=sys.stderr)
            continue

        if completo is not None:
            auction.details = completo.details


def to_record(auction: Auction) -> dict:
    """
    Converte o modelo do tibia.py no dicionario que vai pro JSON.

    O grosso vem do proprio modelo (datas em ISO 8601, enums como texto).
    Os tres ajustes do fim mantem compatibilidade com o formato que o script
    gerava antes: `sex` capitalizado, `url` (que no tibia.py e propriedade,
    nao campo) e `highlights` como lista de strings.
    """
    rec = json.loads(auction.model_dump_json())
    if rec.get("sex"):
        rec["sex"] = rec["sex"].capitalize()
    rec["url"] = str(auction.url)
    rec["highlights"] = [arg["content"] for arg in rec.get("sales_arguments", [])]
    return rec


def main():
    p = argparse.ArgumentParser(description="Scraper do Char Bazaar do Tibia")
    p.add_argument("--vocation", type=int, default=VOCATION,
                   help="0=todas 1=None 2=Druid 3=Knight 4=Paladin 5=Sorcerer 6=Monk "
                        f"(default: {VOCATION})")
    p.add_argument("--world", default=WORLD,
                   help=f'Nome do mundo (default: {WORLD or "todos"}). '
                        'Use --world "" para todos')
    p.add_argument("--level-from", type=int, default=LEVEL_FROM,
                   help=f"Level minimo (default: {LEVEL_FROM}, 0 = sem minimo)")
    p.add_argument("--level-to", type=int, default=LEVEL_TO,
                   help=f"Level maximo (default: {LEVEL_TO}, 0 = sem maximo)")
    p.add_argument("--max-pages", type=int, default=MAX_PAGES,
                   help="Limita quantas paginas raspar (util pra testar)")
    p.add_argument("--limit", type=int, default=LIMIT,
                   help="Traz apenas os N primeiros resultados (ex: 10)")
    p.add_argument("--delay", type=float, default=DELAY,
                   help=f"Pausa entre requisicoes em segundos (default {DELAY})")
    p.add_argument("--details", action="store_true", default=DETAILS,
                   help="Abre a pagina de cada leilao e traz a ficha completa "
                        "(skills, itens, charms...). Custa 1 requisicao por leilao")
    p.add_argument("--json", metavar="ARQUIVO",
                   help='Salva o resultado em JSON. Use --json - pra jogar o '
                        'JSON no stdout (util pra pipe / n8n)')
    args = p.parse_args()

    session = requests.Session()
    auctions = scrape(
        vocation=args.vocation,
        world=args.world,
        level_from=args.level_from,
        level_to=args.level_to,
        max_pages=args.max_pages,
        delay=args.delay,
        limit=args.limit,
        session=session,
    )

    if args.details and auctions:
        fetch_details(session, auctions, delay=args.delay)

    payload = [to_record(a) for a in auctions]

    # "--json -" e modo pipe: JSON puro no stdout, sem arquivo e sem texto solto.
    if args.json == "-":
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return

    # --- terminal ---
    if PRINT_JSON:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"\n=== {len(payload)} leiloes encontrados ===\n")
        for a in payload:
            bid_str = f"{a['bid']:,}".replace(",", ".") if a["bid"] else "-"
            print(f"[{a['auction_id']}] {a['name']} | Lvl {a['level']} {a['vocation']} "
                  f"| {a['world']} | {a['bid_type'] or ''} {bid_str}")

    # --- arquivo ---
    # Sem --json, o nome sai automatico com mundo + timestamp, entao cada
    # rodada gera um arquivo novo em vez de sobrescrever o anterior.
    destino = args.json
    if not destino and SAVE_JSON:
        mundo = (args.world or "todos").lower()
        carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
        destino = Path(OUTPUT_DIR) / f"bazaar_{mundo}_{carimbo}.json"

    if destino:
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n[i] {len(payload)} leiloes salvos em {destino.resolve()}",
              file=sys.stderr)


if __name__ == "__main__":
    main()
