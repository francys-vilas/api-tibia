# tibia-bazaar-scraper

Scraper do [Char Bazaar oficial do Tibia](https://www.tibia.com/charactertrade/).
Raspa os leiloes ativos com os mesmos filtros da pagina oficial (vocacao, mundo,
level) e devolve os dados estruturados, com paginacao automatica.

O parse do HTML fica por conta da biblioteca [tibia.py](https://tibiapy.readthedocs.io/),
usada so na parte de parsing (as requisicoes continuam sendo feitas com
`requests`, de forma sincrona). Isso tira daqui a manutencao das regex e traz
campos tipados: datas viram `datetime`, vocacao e status viram enum.

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

### Configuracao

Os filtros padrao ficam num bloco de variaveis no topo do
[`tibia_bazaar_scraper.py`](tibia_bazaar_scraper.py), logo abaixo dos imports:

```python
WORLD = "Calmera"       # nome exato do mundo (case-sensitive); "" = todos
VOCATION = 0            # 0=todas 1=None 2=Druid 3=Knight 4=Paladin 5=Sorcerer 6=Monk
LEVEL_FROM = 0          # 0 = sem minimo
LEVEL_TO = 0            # 0 = sem maximo
LIMIT = None            # None = traz tudo; N = para nos N primeiros
MAX_PAGES = None        # None = sem teto de paginas
DELAY = 1.0             # pausa entre requisicoes, em segundos. NAO use 0.
DETAILS = False         # True = abre a pagina de cada leilao (1 requisicao por leilao)

PRINT_JSON = True       # True = mostra o JSON no terminal; False = lista resumida
SAVE_JSON = True        # True = grava um arquivo .json a cada rodada
OUTPUT_DIR = "saida"    # pasta dos arquivos gerados (criada se nao existir)

PVP_TYPE = None         # None = todos | 0=Open 1=Optional 2=Hardcore 3=Retro Open 4=Retro Hardcore
BATTLEYE_STATE = None   # None = todos | 1=Initially Protected 2=Protected 3=Not Protected
ORDER_COLUMN = 101      # 101 = fim do leilao (100=lance 102=level 103=inicio)
ORDER_DIRECTION = 1     # 1 = crescente (quem termina antes vem primeiro)
```

Edite ali pra mudar o padrao de toda rodada. As flags da CLI sobrescrevem
esses valores numa execucao especifica. Os quatro ultimos (`PVP_TYPE`,
`BATTLEYE_STATE`, `ORDER_COLUMN`, `ORDER_DIRECTION`) nao tem flag equivalente:
so dao pra mudar por ali. Um valor invalido agora para o script com mensagem
clara em vez de virar um filtro silenciosamente errado.

### Linha de comando

```powershell
# 10 primeiros leiloes de Calmera
.\.venv\Scripts\python.exe tibia_bazaar_scraper.py --limit 10

# so Knights, exportando pra JSON
.\.venv\Scripts\python.exe tibia_bazaar_scraper.py --vocation 3 --json calmera.json

# outro mundo, ou todos
.\.venv\Scripts\python.exe tibia_bazaar_scraper.py --world Antica
.\.venv\Scripts\python.exe tibia_bazaar_scraper.py --world ""

# com a ficha completa de cada personagem
.\.venv\Scripts\python.exe tibia_bazaar_scraper.py --limit 5 --details
```

Errar o nome do mundo nao passa mais batido. O tibia.com ignora um
`filter_world` que nao reconhece e devolve o bazaar inteiro; o script compara
com a lista de mundos que a propria pagina publica e avisa:

```
[!] 'Clamera' nao esta na lista de 96 mundos do bazaar. Voce quis dizer: Calmera, Gladera, Blumera?
[!] O filtro de mundo foi ignorado pelo tibia.com.
```

### Opcoes

| Flag | Descricao |
| --- | --- |
| `--vocation` | 0=todas 1=None 2=Druid 3=Knight 4=Paladin 5=Sorcerer 6=Monk |
| `--world` | Nome do mundo (default: `Calmera`; `""` = todos) |
| `--level-from` / `--level-to` | Faixa de level |
| `--limit` | Traz apenas os N primeiros (para de paginar cedo) |
| `--max-pages` | Limita quantas paginas raspar |
| `--delay` | Pausa entre requisicoes, em segundos (default 1.0) |
| `--details` | Abre a pagina de cada leilao e traz a ficha completa |
| `--json` | Salva o resultado num arquivo JSON; `--json -` joga no stdout |

### Saida

Rodando sem flag de saida, o script faz as duas coisas: imprime o JSON no
terminal e grava um arquivo novo em `saida/`, com mundo e timestamp no nome
(`saida/bazaar_calmera_20260912-190937.json`). Como o nome carrega a hora,
cada rodada gera um arquivo novo em vez de sobrescrever o anterior.

```powershell
.\.venv\Scripts\python.exe tibia_bazaar_scraper.py
```

| Modo | Terminal | Arquivo |
| --- | --- | --- |
| sem flag | JSON | `saida/bazaar_<mundo>_<timestamp>.json` |
| `--json meu.json` | JSON | `meu.json` (nome fixo, sobrescreve) |
| `--json -` | JSON puro, pra pipe | nenhum |

Os avisos de progresso vao pro stderr, entao `--json -` devolve JSON limpo:

```powershell
.\.venv\Scripts\python.exe tibia_bazaar_scraper.py --json - 2>$null
```

Pra ver a lista resumida em vez do JSON, ponha `PRINT_JSON = False` no bloco
de configuracao. `SAVE_JSON = False` desliga a gravacao automatica.

A ordenacao padrao e por data de fim do leilao (`ORDER_COLUMN = 101`), entao
`--limit 10` traz os 10 que terminam primeiro.

### Campos de cada leilao

Todos os campos que o script ja gerava continuam com o mesmo nome e o mesmo
valor. **A unica mudanca de formato e o `auction_end`**, que passou de string
crua do site (`"Sep 13 2026, 04:00 CEST"`) pra ISO 8601 em UTC
(`"2026-09-13T02:00:00Z"`) - mesmo instante, mas agora da pra ordenar e
comparar sem parsear texto.

| Campo | Exemplo | |
| --- | --- | --- |
| `auction_id` | `2255072` | |
| `name` | `"Torres Iscariotes"` | |
| `level` | `895` | |
| `vocation` | `"Elder Druid"` | |
| `sex` | `"Male"` | |
| `world` | `"Calmera"` | |
| `bid` | `16000` | |
| `bid_type` | `"Minimum Bid"` ou `"Current Bid"` | |
| `auction_end` | `"2026-09-13T02:00:00Z"` | formato novo |
| `url` | link da pagina de detalhe | |
| `highlights` | lista de strings dos destaques | |
| `auction_start` | `"2026-09-11T08:06:00Z"` | novo |
| `status` | `"in progress"` | novo |
| `outfit` | `{outfit_id, addons, image_url}` | novo |
| `displayed_items` | itens em destaque, com `item_id`, `count` e `tier` | novo |
| `sales_arguments` | os mesmos destaques, com `category_id` pra filtrar por tipo | novo |
| `details` | `null`, ou a ficha completa com `--details` | novo |

`highlights` continua existindo (mesmo conteudo de antes) pra nao quebrar quem
ja lia esse campo; `sales_arguments` e a versao estruturada do mesmo dado.

## Ficha completa (`--details`)

Com `--details` o script abre a pagina de cada leilao e preenche o campo
`details`: HP/mana/capacidade/speed, experiencia, data de criacao do char, os
8 skills com nivel e progresso, charm points, boss points, imbuements,
blessings, charms, titulos, quests, achievements, bestiary, bosstiary,
revealed gems, e o inventario (itens, mounts, outfits, familiars).

Duas ressalvas antes de ligar:

- **Custa uma requisicao por leilao**, respeitando o mesmo `--delay`. Raspar
  Calmera inteira com `--details` sao 27 requisicoes a mais. Use junto com
  `--limit` ou com um filtro apertado.
- **O JSON cresce muito**: ~90 KB por leilao (um char antigo tem 675 linhas de
  bestiary). Dois leiloes com ficha completa deram 180 KB.

Listas paginadas (itens, mounts, outfits) trazem so a primeira pagina, que e o
que vem no HTML - junto com `results_count` e `total_pages`, pra ficar claro
quanto ficou de fora. Buscar o resto exigiria requisicoes AJAX adicionais.

### `tibiapy_fixes.py`

O tibia.py 6.4.0 parseia a **listagem** do bazaar sem problema, mas o parser da
**pagina de detalhe** esta defasado em relacao ao tibia.com atual em quatro
pontos - dois estouram exception e dois falham calados, devolvendo lista vazia:

| Parser | Sintoma | Causa |
| --- | --- | --- |
| `_parse_tables` | `KeyError: 'id'` | bloco novo "Fragment Progress" sem `id` |
| `_parse_revealed_gems_table` | `TypeError` | linhas de sub-cabecalho sem `div.Gem` |
| `_parse_charms_table` | devolve `[]` | tabela foi de 2 pra 4 colunas |
| `_parse_bestiary_table` | devolve `[]` | bestiary foi de 3 pra 5 colunas |

O [`tibiapy_fixes.py`](tibiapy_fixes.py) corrige os quatro por monkeypatch,
aplicado so quando `--details` e usado. Os remendos aceitam tanto o formato
velho quanto o novo, entao continuam validos se o tibia.com voltar atras. Quando
sair uma versao do tibia.py com isso resolvido, da pra apagar o arquivo inteiro
e a chamada de `tibiapy_fixes.apply()`.

Como o modelo `CharmEntry` do tibia.py so tem nome e custo, o tipo e o grade do
charm entram no nome: `"Major Curse (Grade 2)"`.

## API (Docker / Coolify)

A pasta [`api/`](api/) expoe o scraper como API HTTP, pra rodar num container e
ser consultada pelo n8n sem Python do outro lado:

```bash
curl "http://localhost:8000/auctions?world=Calmera&vocation=3&limit=10"
```

O ganho nao e so comodidade: a API mantem cache por combinacao de filtros, entao
o tibia.com e consultado no maximo uma vez a cada `CACHE_TTL` (5 min por padrao),
nao importa de quanto em quanto tempo o n8n pergunte.

Endpoints, variaveis de ambiente e o passo a passo do deploy no Coolify estao no
[`api/README.md`](api/README.md).

## n8n

Existem dois workflows, os dois prontos pra importar
(n8n -> menu (...) -> **Import from File**):

| Arquivo | Como funciona |
| --- | --- |
| [`n8n/tibia-bazaar-api-workflow.json`](n8n/tibia-bazaar-api-workflow.json) | consulta a API. 5 nodes, sem parser proprio |
| [`n8n/tibia-bazaar-workflow.json`](n8n/tibia-bazaar-workflow.json) | raspa o tibia.com direto, sem depender de nada |

### Consultando a API

Ajuste o `api_url` no node **Configuracao** pro nome do container da API na rede
interna do Coolify. Detalhes em [`api/README.md`](api/README.md#usando-no-n8n).

### Raspando direto (workflow original)

Nao precisa de Python nem de credencial: usa so nodes nativos, entao roda
igual em self-hosted e na Cloud. Os filtros ficam no node **Configuracao**
(mesmos campos do bloco de configuracao do script; `limit` e `max_pages` com
`0` significam "sem limite"). A saida e um item por leilao.

> Este workflow continua com o parser proprio em JavaScript, que nao passou
> pela migracao pro tibia.py (la nao roda Python). Ele entrega o conjunto
> antigo de campos, com `auction_end` no formato cru do site e sem
> `auction_start`, `status`, `outfit`, `displayed_items` nem `details`.

Os nodes, em ordem:

| Node | Papel |
| --- | --- |
| Configuracao | filtros (mundo, vocacao, level, limite) |
| Buscar pagina 1 | primeira requisicao, so pra saber quantas paginas tem |
| Descobrir paginas | le o `Results: N` e gera um item por pagina |
| Buscar todas as paginas | uma requisicao por pagina, a 1 por segundo |
| Extrair leiloes | parseia o HTML e devolve um item por leilao |

O node **Buscar todas as paginas** vem com batching de 1 requisicao por
segundo, que e o equivalente ao `DELAY` do script. Nao baixe esse intervalo.

## Nota

O `--delay` existe pra nao martelar o servidor da CipSoft. Nao coloque 0.
Com `--details` ele vale tambem pras requisicoes de detalhe.
