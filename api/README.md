# API do Char Bazaar

Expoe o [scraper da raiz do repo](../tibia_bazaar_scraper.py) como API HTTP, pra
o n8n consultar sem precisar de Python nem de parser proprio do outro lado.

Nao tem autenticacao no codigo: a ideia e rodar no Coolify **sem dominio
publico**, so na rede interna do Docker. Quem alcanca a API e quem esta na
mesma rede - o n8n, por exemplo.

## Por que uma API, e nao o n8n raspando direto

O workflow atual do n8n faz uma requisicao por pagina do bazaar toda vez que
roda. Com a API no meio, o tibia.com e consultado no maximo uma vez por
`CACHE_TTL` (5 min por padrao), independente de quantas vezes o n8n perguntar.
E a logica de parsing passa a existir num lugar so.

## Endpoints

| Metodo | Rota | O que faz |
| --- | --- | --- |
| `GET` | `/health` | Healthcheck. Nao toca no tibia.com |
| `GET` | `/worlds` | Os 96 mundos que existem no bazaar (cache de 24h) |
| `GET` | `/auctions` | Lista de leiloes ativos, com filtros |
| `GET` | `/auctions/{auction_id}` | Um leilao com a ficha completa do char |
| `GET` | `/docs` | Documentacao interativa (Swagger), gerada pelo FastAPI |

### `GET /auctions`

| Parametro | Default | Descricao |
| --- | --- | --- |
| `world` | `Calmera` | Nome exato do mundo. Vazio = todos |
| `vocation` | `0` | 0=todas 1=None 2=Druid 3=Knight 4=Paladin 5=Sorcerer 6=Monk |
| `level_from` / `level_to` | `0` | Faixa de level. 0 = sem limite |
| `limit` | `0` | Traz so os N primeiros. 0 = todos |
| `max_pages` | `0` | Teto de paginas a raspar. 0 = sem teto |
| `details` | `false` | Ficha completa de cada char. Exige `limit` <= `DETAILS_MAX` |
| `refresh` | `false` | Ignora o cache e raspa na hora |

A ordenacao e por data de fim do leilao, entao `limit=10` traz os 10 que
terminam primeiro.

```bash
curl "http://localhost:8000/auctions?world=Calmera&vocation=3&limit=10"
```

```json
{
  "count": 10,
  "filters": { "world": "Calmera", "vocation": 3, "...": "..." },
  "cache": {
    "hit": true, "stale": false, "age_seconds": 19.5,
    "ttl_seconds": 300, "fetched_at": "2026-09-12T19:23:48Z"
  },
  "auctions": [ { "auction_id": 2255072, "name": "...", "...": "..." } ]
}
```

Os campos de cada leilao sao os mesmos do script - veja a
[tabela no README da raiz](../README.md#campos-de-cada-leilao).

## Cache

E o motivo de existir a API. Cada combinacao de filtros e uma chave, com
comportamento *stale-while-revalidate*:

| Estado | O que acontece | Tempo de resposta |
| --- | --- | --- |
| Cache fresco | responde direto | ~70 ms |
| Cache vencido | responde com o dado velho **e** atualiza por tras | ~100 ms |
| Cache vazio | raspa na hora (unico caso lento) | 1 s a 2 min |

Ou seja: depois da primeira chamada, o n8n nunca mais espera uma raspagem.
Chamadas simultaneas com a mesma chave aproveitam a mesma raspagem em vez de
dispararem varias - cinco `curl` ao mesmo tempo com cache vazio geraram uma
raspagem so.

O campo `cache` da resposta diz em que situacao voce caiu.

## Variaveis de ambiente

| Variavel | Default | Pra que serve |
| --- | --- | --- |
| `CACHE_TTL` | `300` | Segundos que um resultado vale antes de virar stale |
| `WORLDS_TTL` | `86400` | Idem pra `/worlds`, que muda raro |
| `DEFAULT_WORLD` | `Calmera` | Mundo usado quando a chamada nao passa `world` |
| `SCRAPER_DELAY` | `1.0` | Pausa entre requisicoes ao tibia.com. **Nao use 0** |
| `DETAILS_MAX` | `50` | Teto de leiloes por chamada com `details=true` |

## Deploy no Coolify

### 0. Pôr o repo num Git que o Coolify alcance

O Coolify puxa o codigo de GitHub/GitLab/Gitea - nao da pra apontar pra uma
pasta local. Se `git remote -v` nao devolver nada, comece por aqui:

```powershell
git add -A
git commit -m "API do bazaar"
git remote add origin git@github.com:<voce>/tibia-bazaar-scraper.git
git push -u origin master
```

Repo publico: basta colar a URL no Coolify. Repo privado: precisa conectar uma
GitHub App (ou deploy key) no Coolify antes, em **Sources**.

### 1. Criar a aplicacao

**Project -> + New -> Application**, escolher o servidor, e apontar pro repo
(*Public Repository* ou *Private Repository*, conforme o passo 0). Branch:
`master`.

### 2. Configuration -> General

| Campo | Valor | Por que |
| --- | --- | --- |
| Build Pack | `Dockerfile` | |
| Base Directory | `/` | e o contexto do build; a imagem precisa do `tibia_bazaar_scraper.py`, que esta na raiz |
| Dockerfile Location | `/api/Dockerfile` | caminho relativo ao Base Directory |
| Ports Exposes | `8000` | |
| Domains | **deixar vazio** | sem FQDN, o proxy nao publica a aplicacao e ela fica so na rede interna |

**Nao crie Port Mappings.** Mapear porta publica a aplicacao no IP do servidor,
que e justamente o que nao queremos (nao ha autenticacao no codigo).

### 3. Configuration -> Advanced: nome fixo pro container

O nome do container e o hostname que o n8n vai usar. Por padrao o Coolify gera
um nome com sufixo aleatorio, que muda. Em **Advanced -> Container & Proxy**:

- **Custom Container Name**: `tibia-bazaar-api`
- **Consistent Container Names**: ligado

Assim o `api_url` que ja vem no workflow (`http://tibia-bazaar-api:8000`)
funciona sem ajuste.

### 4. Environment Variables

Nenhuma e obrigatoria - os defaults da tabela acima ja servem. Vale a pena
mexer em `DEFAULT_WORLD` se o seu mundo nao for Calmera, e em `CACHE_TTL` se
quiser dados mais frescos (ou menos requisicoes ao tibia.com).

### 5. Deploy

Botao **Deploy**. O primeiro build demora alguns minutos (compila as deps).
Acompanhe em **Logs**; quando o healthcheck ficar verde, esta no ar.

### Alternativa: subir a imagem pronta, sem Git

Se voce nao quer o codigo num Git, da pra construir a imagem aqui e mandar so
ela. O Coolify tem um tipo de recurso **Docker Image**, que roda uma imagem de
registry em vez de construir a partir de um repo.

Na sua maquina (a partir da raiz do repo):

```powershell
# --platform garante uma imagem linux/amd64, que e o que o servidor roda
docker build --platform linux/amd64 -f api/Dockerfile -t <usuario>/tibia-bazaar-api:1.0.0 .
docker login
docker push <usuario>/tibia-bazaar-api:1.0.0
```

No Coolify: **Project -> + New -> Docker Image**, com a imagem
`<usuario>/tibia-bazaar-api:1.0.0` e `Ports Exposes` = `8000`. Continua valendo
o resto: sem Domains, sem Port Mappings, e confira o nome do container pra
acertar o `api_url` do n8n.

Registry privado: o Coolify nao guarda credencial de registry - ele usa o login
do Docker do proprio servidor. Entre por SSH na maquina do Coolify e rode
`docker login <registry>` uma vez; depois disso ele consegue puxar. O Coolify
tambem tem um servico one-click de **Docker Registry** proprio, se voce preferir
nao usar Docker Hub nem GHCR.

O que voce perde nessa rota: **auto-deploy**. Com Git, um `git push` dispara o
build e o deploy sozinho. Com imagem, cada mudanca vira build + push + trocar a
tag no Coolify + redeploy, tudo na mao. Em compensacao, o build roda na sua
maquina, e nao no servidor.

E vale lembrar que **Git nao quer dizer GitHub**: o Coolify aceita GitLab,
Gitea, Bitbucket ou qualquer repo por deploy key - inclusive um Gitea
self-hosted no mesmo servidor.

### Sobre a rede: quem precisa de "Connect To Predefined Network"

Aplicacao com build pack **Dockerfile entra na rede `coolify` sozinha** - nao
precisa mexer nessa opcao. Ela existe pra recursos **Docker Compose**, que
sobem numa rede propria e isolada.

Isso importa pro outro lado: **se o seu n8n foi criado como Service ou Docker
Compose no Coolify** (o caso do one-click), e ele que esta na rede isolada e
nao enxerga a API. A solucao e ligar **Connect To Predefined Network** *no
n8n*, nao aqui. Se o n8n tambem for uma Application comum, os dois ja estao na
mesma rede.

Se o n8n roda fora desse servidor, ai nao tem rede interna: seria preciso expor
a API com dominio e pôr autenticacao antes - o que este projeto nao faz hoje.

### Conferindo depois do deploy

De dentro do container do n8n (Coolify -> o recurso do n8n -> **Terminal**):

```bash
curl "http://tibia-bazaar-api:8000/health"
curl "http://tibia-bazaar-api:8000/auctions?world=Calmera&limit=3"
```

O primeiro tem que responder `{"status":"ok",...}` na hora. Se der
`could not resolve host`, o problema e de rede - veja a secao acima.

## Usando no n8n

Importe [`n8n/tibia-bazaar-api-workflow.json`](../n8n/tibia-bazaar-api-workflow.json)
(n8n -> menu (...) -> **Import from File**). Sao 5 nodes:

| Node | Papel |
| --- | --- |
| Executar manualmente | trigger pra testar na mao |
| A cada 15 minutos | trigger agendado, pra consulta periodica |
| Configuracao | `api_url` e os filtros |
| Consultar API | `GET {api_url}/auctions` com os filtros como query |
| Separar leiloes | quebra o campo `auctions` em um item por leilao |

O `api_url` ja vem como `http://tibia-bazaar-api:8000`, que casa com o
**Custom Container Name** do passo 3. Se voce deu outro nome ao container,
ajuste o `api_url` no node **Configuracao**.

O intervalo de 15 minutos do trigger nao tem relacao com a carga no tibia.com:
quem decide isso e o `CACHE_TTL`. Da pra consultar de minuto em minuto sem
raspar mais por causa disso.

Esse workflow substitui o [`tibia-bazaar-workflow.json`](../n8n/tibia-bazaar-workflow.json),
que continua no repo pra quem quiser rodar sem a API - mas ele tem parser
proprio em JavaScript e entrega o conjunto antigo de campos.

## Rodando local

Com Docker:

```powershell
docker compose -f api/docker-compose.yaml up --build
curl "http://localhost:8000/auctions?world=Calmera&limit=5"
```

Sem Docker, a partir da raiz do repo:

```powershell
.\.venv\Scripts\python.exe -m pip install -r api/requirements.txt
.\.venv\Scripts\python.exe -m uvicorn api.main:app --reload
```

Em ambos os casos, `http://localhost:8000/docs` abre o Swagger.

## Ressalvas

- **Sem `world`, a primeira chamada demora.** Sao ~2600 leiloes em mais de 100
  paginas, a 1 requisicao por segundo: uns 2 minutos. O `timeout` do node do
  n8n ja vem em 180 s por causa disso. Com cache quente, responde na hora.
- **`details=true` custa uma requisicao por leilao.** Por isso exige `limit`
  de no maximo `DETAILS_MAX` (50). E o JSON cresce ~90 KB por leilao.
- **O cache vive na memoria do processo.** Reiniciou o container, o cache
  comeca vazio. Pra varias replicas ou cache que sobrevive a restart, seria
  caso de Redis - hoje nao tem.
- **`SCRAPER_DELAY` nao e enfeite.** Ele existe pra nao martelar o servidor da
  CipSoft. Nao ponha 0.
