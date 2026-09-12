#!/usr/bin/env python3
"""
Tibia Char Bazaar Scraper
==========================
Raspa os leilões ativos do Char Bazaar oficial (tibia.com) e devolve
os dados estruturados. Suporta os mesmos filtros da página oficial
(vocação, mundo, level, skill, etc.) e paginação automática.

Uso basico:
    pip install requests beautifulsoup4
    python tibia_bazaar_scraper.py

Exemplos:
    # Knights (vocation=3) no mundo Calmera
    python tibia_bazaar_scraper.py --vocation 3 --world Calmera

    # Exporta pra JSON
    python tibia_bazaar_scraper.py --vocation 3 --world Calmera --json saida.json

Codigos de vocacao (filter_profession):
    0 = todas | 1 = None | 2 = Druid | 3 = Knight | 4 = Paladin | 5 = Sorcerer | 6 = Monk

    (Obs: no Exevo Pan a numeracao e diferente. No tibia.com oficial
     o parametro e "filter_profession". Confira sempre pela pagina real.)
"""

import argparse
import json
import re
import time
import sys
from dataclasses import dataclass, asdict, field
from typing import Optional

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.tibia.com/charactertrade/"

# Um User-Agent de navegador de verdade evita bloqueios simples.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}


@dataclass
class Auction:
    auction_id: int
    name: str
    level: Optional[int] = None
    vocation: Optional[str] = None
    sex: Optional[str] = None
    world: Optional[str] = 'Calmera'
    bid: Optional[int] = None
    bid_type: Optional[str] = None          # "Current Bid" ou "Minimum Bid"
    auction_end: Optional[str] = None
    url: Optional[str] = None
    highlights: list = field(default_factory=list)  # skills, charm points, etc.


def _clean(text: str) -> str:
    """A pagina usa espaco nao-separavel (\\xa0) nas datas; normaliza pra espaco."""
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def fetch_page(session: requests.Session, params: dict) -> str:
    """Baixa uma pagina do bazaar. Retorna o HTML cru."""
    resp = session.get(BASE_URL, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_auctions(html: str) -> list[Auction]:
    """
    Extrai todos os leiloes de uma pagina de HTML.
    A pagina do tibia.com usa uma tabela com classe 'Auction' por leilao.
    """
    soup = BeautifulSoup(html, "html.parser")
    auctions: list[Auction] = []

    # Cada leilao vive dentro de um bloco <div class="Auction">
    for block in soup.select("div.Auction"):
        # --- ID e nome (link de detalhes) ---
        header = block.select_one(".AuctionCharacterName a")
        if not header:
            continue
        name = header.get_text(strip=True)
        id_match = re.search(r"auctionid=(\d+)", header.get("href", ""))
        auction_id = int(id_match.group(1)) if id_match else -1
        # O href da pagina traz "&currentpage=", que o parser de HTML decodifica
        # como a entidade &curren; e corrompe a URL. Remontar pelo id evita isso.
        full_url = (
            f"{BASE_URL}?subtopic=currentcharactertrades"
            f"&page=details&auctionid={auction_id}"
        )

        # --- Level / Vocacao / Sexo / Mundo ---
        # Linha unica tipo:
        #   "Nome Level: 754 | Vocation: Elite Knight | Male | World: Issobra"
        head = block.select_one(".AuctionHeader")
        header_text = _clean(head.get_text(" ", strip=True)) if head else ""

        def grab(pattern):
            m = re.search(pattern, header_text)
            return m.group(1).strip() if m else None

        level = grab(r"Level:\s*(\d+)")
        vocation = grab(r"Vocation:\s*(.+?)\s*\|")
        sex = grab(r"\|\s*(Male|Female)\s*\|")
        world = grab(r"World:\s*(\w+)")

        # --- Datas e lance: vem como pares rotulo/valor, nao como texto corrido ---
        short_data = {}
        for lbl in block.select(".ShortAuctionDataLabel"):
            val = lbl.find_next(class_="ShortAuctionDataValue")
            if val is None:
                continue
            key = _clean(lbl.get_text(" ", strip=True)).rstrip(":")
            short_data[key] = _clean(val.get_text(" ", strip=True))

        auction_end = short_data.get("Auction End")

        bid_type = None
        bid = None
        for label in ("Current Bid", "Minimum Bid"):
            raw = short_data.get(label)
            if raw:
                bid_type = label
                bid = int(re.sub(r"[^\d]", "", raw))
                break

        # --- Destaques (skills, charm points, boss points...) ---
        highlights = []
        for feat in block.select(".Entry"):
            txt = _clean(feat.get_text(" ", strip=True))
            if txt:
                highlights.append(txt)

        auctions.append(
            Auction(
                auction_id=auction_id,
                name=name,
                level=int(level) if level else None,
                vocation=vocation,
                sex=sex,
                world=world,
                bid=bid,
                bid_type=bid_type,
                auction_end=auction_end,
                url=full_url,
                highlights=highlights,
            )
        )

    return auctions


def get_total_pages(html: str) -> int:
    """Le o numero da ultima pagina a partir do link 'Last Page'."""
    m = re.search(r"currentpage=(\d+)[^>]*>\s*(?:Last Page|»\s*Last)", html)
    if m:
        return int(m.group(1))
    # fallback: procura o maior currentpage que aparecer
    nums = [int(n) for n in re.findall(r"currentpage=(\d+)", html)]
    return max(nums) if nums else 1


def scrape(vocation=0, world="", level_from=0, level_to=0,
           max_pages=None, delay=1.0, limit=None) -> list[Auction]:
    """
    Raspa o bazaar inteiro (ou parte dele) com os filtros dados.

    delay = pausa em segundos entre requisicoes. NAO reduza pra 0:
            ser educado com o servidor da CipSoft evita bloqueio.
    """
    session = requests.Session()

    base_params = {
        "subtopic": "currentcharactertrades",
        "filter_profession": vocation,
        "filter_world": world,
        "filter_levelrangefrom": level_from,
        "filter_levelrangeto": level_to,
        "filter_worldpvptype": 9,        # 9 = todos
        "filter_worldbattleyestate": 0,  # 0 = todos
        "order_column": 101,             # 101 = por data de fim
        "order_direction": 1,
        "searchtype": 1,
    }

    # Primeira pagina: descobre quantas paginas existem
    first_html = fetch_page(session, {**base_params, "currentpage": 1})
    total = get_total_pages(first_html)
    if max_pages:
        total = min(total, max_pages)

    print(f"[i] Total de paginas a raspar: {total}", file=sys.stderr)

    all_auctions = parse_auctions(first_html)
    print(f"[i] Pagina 1/{total}: {len(all_auctions)} leiloes", file=sys.stderr)

    # Com --limit nao adianta baixar o resto: para assim que tiver o bastante.
    if limit and len(all_auctions) >= limit:
        return all_auctions[:limit]

    for page in range(2, total + 1):
        time.sleep(delay)  # <-- educacao com o servidor
        html = fetch_page(session, {**base_params, "currentpage": page})
        page_auctions = parse_auctions(html)
        all_auctions.extend(page_auctions)
        print(f"[i] Pagina {page}/{total}: {len(page_auctions)} leiloes", file=sys.stderr)
        if limit and len(all_auctions) >= limit:
            break

    return all_auctions[:limit] if limit else all_auctions


def main():
    p = argparse.ArgumentParser(description="Scraper do Char Bazaar do Tibia")
    p.add_argument("--vocation", type=int, default=0,
                   help="0=todas 1=None 2=Druid 3=Knight 4=Paladin 5=Sorcerer 6=Monk")
    p.add_argument("--world", default="", help="Nome do mundo (ex: Calmera)")
    p.add_argument("--level-from", type=int, default=0)
    p.add_argument("--level-to", type=int, default=0)
    p.add_argument("--max-pages", type=int, default=None,
                   help="Limita quantas paginas raspar (util pra testar)")
    p.add_argument("--limit", type=int, default=None,
                   help="Traz apenas os N primeiros resultados (ex: 10)")
    p.add_argument("--delay", type=float, default=1.0,
                   help="Pausa entre requisicoes em segundos (default 1.0)")
    p.add_argument("--json", metavar="ARQUIVO", help="Salva o resultado em JSON")
    args = p.parse_args()

    auctions = scrape(
        vocation=args.vocation,
        world=args.world,
        level_from=args.level_from,
        level_to=args.level_to,
        max_pages=args.max_pages,
        delay=args.delay,
        limit=args.limit,
    )

    print(f"\n=== {len(auctions)} leiloes encontrados ===\n")
    for a in auctions:
        bid_str = f"{a.bid:,}".replace(",", ".") if a.bid else "-"
        print(f"[{a.auction_id}] {a.name} | Lvl {a.level} {a.vocation} "
              f"| {a.world} | {a.bid_type or ''} {bid_str}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump([asdict(a) for a in auctions], f, ensure_ascii=False, indent=2)
        print(f"\n[i] Salvo em {args.json}", file=sys.stderr)


if __name__ == "__main__":
    main()
