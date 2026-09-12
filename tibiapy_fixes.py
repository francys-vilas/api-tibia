#!/usr/bin/env python3
"""
Remendos no parser de leiloes do tibia.py
==========================================
O tibia.py 6.4.0 (ultima versao no PyPI em setembro/2026) parseia a LISTAGEM
do bazaar perfeitamente. Ja a pagina de DETALHE de um leilao mudou no
tibia.com e o parser ficou pra tras em quatro pontos:

  1. _parse_tables           -> estoura KeyError: 'id'
     Apareceu um bloco "Fragment Progress" sem atributo id, e o parser
     assume que todo div.CharacterDetailsBlock tem um.
  2. _parse_revealed_gems_table -> estoura TypeError
     A tabela de gems ganhou linhas sem div.Gem (sub-cabecalhos).
  3. _parse_charms_table     -> falha CALADA, devolve lista vazia
     A tabela foi de 2 pra 4 colunas (Costs, Type, Charm Name, Grade) e o
     parser descarta toda linha que nao tenha exatamente 2.
  4. _parse_bestiary_table   -> falha CALADA no bestiary (bosstiary ainda ok)
     Bestiary foi de 3 pra 5 colunas (ganhou Mastery e Echo Warden).

As duas ultimas sao as piores: nao dao erro, so devolvem [] como se o
personagem nao tivesse charm nem bestiary.

Uso:
    import tibiapy_fixes
    tibiapy_fixes.apply()      # antes de chamar AuctionParser.from_content()

Os remendos aceitam tanto o formato velho quanto o novo, entao continuam
funcionando se o tibia.com voltar atras ou se o tibia.py corrigir upstream.
Quando sair uma versao do tibia.py com isso resolvido, da pra apagar este
arquivo inteiro e a chamada de apply().
"""

from tibiapy.builders.bazaar import AuctionDetailsBuilder
from tibiapy.models.bazaar import BestiaryEntry, CharmEntry, RevealedGem
from tibiapy.parsers.bazaar import AuctionParser
from tibiapy.utils import get_rows, parse_integer

import bs4

_applied = False


def _parse_tables(cls, parsed_content: bs4.Tag) -> dict[str, bs4.Tag]:
    """Igual ao original, mas ignora bloco sem id em vez de estourar."""
    return {
        block["id"]: block
        for block in parsed_content.select("div.CharacterDetailsBlock")
        if block.get("id")
    }


def _parse_revealed_gems_table(cls, builder: AuctionDetailsBuilder, table: bs4.Tag) -> None:
    """Igual ao original, mas pula linha que nao seja de gem."""
    table_content = table.select_one("table.TableContent")
    if table_content is None:
        return

    for row in get_rows(table_content):
        gem_tag = row.select_one("div.Gem")
        if gem_tag is None or not gem_tag.get("title"):
            continue  # cabecalho ou sub-cabecalho

        builder.add_revealed_gem(RevealedGem(
            gem_type=gem_tag["title"],
            mods=[span.text for span in row.select("span")],
        ))


def _parse_charms_table(cls, builder: AuctionDetailsBuilder, table: bs4.Tag) -> None:
    """
    Aceita o layout de 2 colunas (antigo) e o de 4 (atual).

    O modelo CharmEntry do tibia.py so tem nome e custo, entao o tipo e o
    grade entram no nome: "Major Curse (Grade 2)".
    """
    table_content = table.select_one("table.TableContent")
    if table_content is None:
        return

    _, *rows = get_rows(table_content)  # primeira linha e o cabecalho
    charms = []
    for row in rows:
        cols = [c.text.strip() for c in row.select("td")]
        if len(cols) == 2:
            cost_c, name = cols
            charm_type = grade = ""
        elif len(cols) >= 4:
            cost_c, charm_type, name, grade = cols[:4]
        else:
            continue

        full_name = f"{charm_type} {name}".strip()
        if grade:
            full_name += f" (Grade {grade})"

        cost = parse_integer(cost_c.replace("x", ""), None)
        if cost is None:
            continue  # linha sem custo numerico: nao e charm

        charms.append(CharmEntry(name=full_name, cost=cost))

    builder.charms(charms)


def _parse_bestiary_table(cls, builder: AuctionDetailsBuilder, table: bs4.Tag,
                          bosstiary: bool = False) -> None:
    """
    Aceita 3 colunas (bosstiary) ou 5 (bestiary, que ganhou Mastery e Echo
    Warden). As tres primeiras - step, kills, nome - sao as unicas que o
    modelo BestiaryEntry guarda.
    """
    table_content = table.select_one("table.TableContent")
    if table_content is None:
        return

    _, *rows = get_rows(table_content)
    bestiary = []
    for row in rows:
        cols = [c.text.strip() for c in row.select("td")]
        if len(cols) < 3:
            continue

        step_c, kills_c, name = cols[:3]
        step = parse_integer(step_c, None)
        kills = parse_integer(kills_c.replace("x", ""), None)
        if step is None or kills is None:
            continue  # cabecalho intermediario ou linha de "more entries"

        bestiary.append(BestiaryEntry(name=name, kills=kills, step=step))

    if bosstiary:
        builder.bosstiary_progress(bestiary)
    else:
        builder.bestiary_progress(bestiary)


def apply() -> None:
    """Aplica os remendos no AuctionParser. Chamar mais de uma vez nao faz mal."""
    global _applied
    if _applied:
        return

    AuctionParser._parse_tables = classmethod(_parse_tables)
    AuctionParser._parse_revealed_gems_table = classmethod(_parse_revealed_gems_table)
    AuctionParser._parse_charms_table = classmethod(_parse_charms_table)
    AuctionParser._parse_bestiary_table = classmethod(_parse_bestiary_table)
    _applied = True
