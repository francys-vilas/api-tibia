# tibia-bazaar-scraper

Scraper do [Char Bazaar oficial do Tibia](https://www.tibia.com/charactertrade/).
Raspa os leiloes ativos com os mesmos filtros da pagina oficial (vocacao, mundo,
level) e devolve os dados estruturados, com paginacao automatica.

> Nao confundir com `C:\repositorio-js\tibia-bazaar-scraper`, que e um clone
> arquivado de terceiros (xandjiji/exevo-pan). Este aqui e o script proprio.

## Setup

O Python global desta maquina esta com o pacote `idna` corrompido, entao o venv
nao e opcional:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Uso

```powershell
# 10 primeiros leiloes do mundo Calmera
.\.venv\Scripts\python.exe tibia_bazaar_scraper.py --world Calmera --limit 10

# so Knights, exportando pra JSON
.\.venv\Scripts\python.exe tibia_bazaar_scraper.py --world Calmera --vocation 3 --json calmera.json
```

### Opcoes

| Flag | Descricao |
| --- | --- |
| `--vocation` | 0=todas 1=None 2=Druid 3=Knight 4=Paladin 5=Sorcerer 6=Monk |
| `--world` | Nome do mundo (ex: `Calmera`) |
| `--level-from` / `--level-to` | Faixa de level |
| `--limit` | Traz apenas os N primeiros (para de paginar cedo) |
| `--max-pages` | Limita quantas paginas raspar |
| `--delay` | Pausa entre requisicoes, em segundos (default 1.0) |
| `--json` | Salva o resultado num arquivo JSON |

A ordenacao e fixa por data de fim do leilao (`order_column=101`), entao
`--limit 10` traz os 10 que terminam primeiro.

## Nota

O `--delay` existe pra nao martelar o servidor da CipSoft. Nao coloque 0.
