# Bank Reconciliation & Anomaly Detection

Plataforma que concilia extratos bancários com notas fiscais e aponta transações incomuns
para investigação humana.

O projeto se apoia em três pontos:

1. **Dados realistas.** Um gerador sintético cria uma empresa fictícia, com padrões de
   pagamento e ruído do mundo real, e registra num gabarito tudo o que deveria ser
   encontrado.
2. **Conciliação que trata casos difíceis.** São três camadas (exata, tolerante e várias
   notas para um pagamento), e cada transação sai com status e confiança.
3. **Anomalias medidas e explicadas.** Um Isolation Forest sobre poucas features legíveis
   gera o ranking, e essas mesmas features viram os motivos exibidos ao analista.

> **O sistema não afirma que uma transação é fraude.** Ele indica o que merece
> investigação humana. O score é mostrado como posição no ranking ("entre as 2% mais
> incomuns") e **não é uma probabilidade de fraude**.

## Como funciona

```
gerador ──► conciliação ──► anomalias ──► Postgres ──► API (FastAPI) ──► página (Next.js)
   │             │              │
   └─ gabarito ──┴──► avaliação ◄┘
```

| Etapa | O que faz |
| --- | --- |
| `generate` | 30 fornecedores com perfis (valor médio, variação, frequência semanal, mensal ou esporádica e dia típico de pagamento), 12 meses de notas e o extrato correspondente. Adiciona ruído (atraso, tarifa descontada, pagamento de várias notas, descrição abreviada como `PIX ACME LOGIST LT`) e injeta anomalias (duplicata, valor fora do padrão, fornecedor novo com valor alto, dia atípico). Com a mesma seed, gera sempre os mesmos dados. |
| `reconcile` | **Camada 1, exata:** mesmo valor, nome prefixo do fornecedor, pagamento até 5 dias depois da nota. **Camada 2, tolerante:** tarifa de até R$ 15, nome comparado com `rapidfuzz` e atraso de até 30 dias. **Camada 3, várias notas:** combinações de notas abertas do mesmo fornecedor que somam o valor pago. Cada camada só vê o que as anteriores deixaram em aberto. |
| `detect` | Calcula as features por pagamento: valor vs. típico do fornecedor, valor vs. mediana da empresa, intervalo curto desde o último pagamento, fornecedor novo, pagamento repetido, fim de semana e fora do ciclo. Depois roda o Isolation Forest, monta o ranking e escreve os motivos em português. |
| `evaluate` | Compara os resultados com o gabarito e imprime as tabelas abaixo. |

Cada transação conciliada sai com um destes status:

- `conciliada`: casou na camada 1, ou nas camadas 2 e 3 com confiança alta e sem ambiguidade;
- `sugerida`: casamento provável que aguarda aprovação humana;
- `divergente`: nenhuma nota correspondente.

Exemplos de motivos gerados:

- *outro pagamento de mesmo valor ao mesmo fornecedor 2 dias antes*
- *valor 5,0 vezes acima do normal para o fornecedor*
- *fornecedor cadastrado há 10 dias* + *valor 25,6 vezes a mediana dos pagamentos da empresa*
- *pago num sábado* + *fora do ciclo do fornecedor (normalmente pago às terças)*

## Como rodar

### Demo completa com Docker

```bash
docker compose up --build
```

Abra http://localhost:3000. Na primeira subida, a API gera os dados sintéticos, roda a
conciliação e a detecção e carrega o Postgres. Nas subidas seguintes, ela reaproveita o
banco, e as revisões feitas na página são mantidas. A documentação interativa da API fica
em http://localhost:8000/docs.

Se as portas 3000 ou 8000 já estiverem em uso, troque as portas do host:

```bash
WEB_PORT=3010 API_PORT=8010 docker compose up --build
```

A página mostra:

- os totais no topo (conciliadas, sugeridas, divergentes e alto risco), que também
  funcionam como filtro;
- a lista de transações, com filtros por status e por faixa de score, busca e ordenação;
- um painel lateral com a posição no ranking, os motivos, as notas casadas e os botões
  para aprovar ou rejeitar uma sugestão.

### API

| Método | Rota | O que faz |
| --- | --- | --- |
| `GET` | `/api/summary` | Totais por status e quantidade de alto risco |
| `GET` | `/api/transactions` | Lista paginada com os filtros `status`, `high_risk`, `max_percentile` (0.1 = top 10%), `q` (busca na descrição ou no ID), `sort` (`risco`, `data` ou `valor`), `limit` e `offset` |
| `GET` | `/api/transactions/{id}` | Detalhe com todos os motivos e as notas casadas |
| `POST` | `/api/transactions/{id}/approve` | Confirma uma sugestão (`409` se não for `sugerida`) |
| `POST` | `/api/transactions/{id}/reject` | Rejeita uma sugestão; as notas voltam a ficar em aberto |

O banco tem as tabelas `suppliers`, `invoices`, `bank_transactions`, `matches` (com a
camada, a confiança e quem decidiu: `sistema` ou `analista`), `match_invoices` (as notas
de cada transação) e `anomaly_scores`.

### Pipeline em Python, sem Docker

Requer Python 3.11+.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cd ..

bankrecon generate          # data/ com notas, extrato e gabarito (seed 42)
bankrecon reconcile         # data/results/matches.csv
bankrecon detect            # data/results/anomaly_scores.csv
bankrecon evaluate          # tabelas de resultado em Markdown
```

Use `bankrecon generate --help` para trocar a seed, o período ou a quantidade de
fornecedores e de anomalias. Cada resultado guarda uma impressão digital dos dados de
entrada, e `detect` e `evaluate` se recusam a usar resultados gerados a partir de outros
dados.

Para servir a API localmente sobre SQLite:

```bash
bankrecon demo                                            # gera, processa e carrega data/bankrecon.db
uvicorn --factory bankrecon.api.app:create_app --port 8000
cd frontend && npm install && npm run dev                 # http://localhost:3000
```

`bankrecon load-db` recarrega o banco a partir dos resultados. Ele se recusa a apagar
revisões feitas por analistas, a menos que receba `--discard-reviews`.

## Resultados

Números reais da seed 42 (608 transações, 658 notas, 32 anomalias injetadas, 8 de cada
tipo), gerados por `bankrecon evaluate`.

### Conciliação

Acerto geral: **99,7%**, contando como acerto o conjunto exato de notas casadas ou a
ausência correta de nota.

| Camada | Transações | Corretas | Acerto |
| --- | --- | --- | --- |
| 1. Exata | 420 | 420 | 100% |
| 2. Tolerante | 146 | 145 | 99% |
| 3. Várias notas | 33 | 33 | 100% |

| Status | Transações | Participação | Corretas |
| --- | --- | --- | --- |
| conciliada | 573 | 94% | 572 |
| sugerida | 26 | 4% | 26 |
| divergente | 9 | 1% | 8 |

| Caso difícil | Transações | Acerto |
| --- | --- | --- |
| Sem ruído | 424 | 100% |
| Pagamento atrasado | 51 | 100% |
| Tarifa descontada | 40 | 98% |
| Várias notas | 33 | 100% |
| Descrição abreviada | 73 | 99% |

### Anomalias

"Alto risco" são as 5% transações de maior score (30). O top 10% tem 61 transações.

| Tipo de anomalia | Injetadas | Recall (alto risco) | Recall (top 10%) |
| --- | --- | --- | --- |
| Pagamento duplicado | 8 | 100% | 100% |
| Valor fora do padrão | 8 | 62% | 75% |
| Fornecedor novo com valor alto | 8 | 100% | 100% |
| Dia atípico | 8 | 62% | 62% |

**Priorização:** a precisão nas 50 transações de maior score é de **54%**. Como há só 32
anomalias, o máximo possível seria 64%. Escolhendo 50 transações ao acaso, o esperado
seria cerca de 5%.

Em outras seeds (1, 2 e 3) os números ficam na mesma faixa:

- conciliação entre 99,7% e 100%;
- recall no top 10%: 100% para duplicatas, 88–100% para valor fora do padrão, 100% para
  fornecedor novo e 62% para dia atípico;
- precisão@50 entre 52% e 56%.

## Limitações

- **Dia atípico tem o recall mais baixo.** Quando o pagamento atípico cai num fim de
  semana, ele é quase sempre encontrado, porque nenhum pagamento normal cai em fim de
  semana. Já o pagamento "fora do ciclo" num dia útil se parece com um pagamento atrasado
  legítimo, que também sai do ciclo. As features não têm como distinguir os dois, e é por
  isso que esse tipo fica perto de 60%.
- **Valor fora do padrão perde para fornecedores muito variáveis.** Um valor 3× acima do
  típico chama atenção num contrato fixo. Num fornecedor que já varia 25%, o mesmo valor
  compete com outros sinais e às vezes cai abaixo do corte de alto risco. No top 10% o
  recall sobe para 75–100%.
- **Fornecedores legítimos recém-cadastrados geram falsos positivos.** "Fornecedor novo"
  sozinho não é anomalia, e o gerador cria fornecedores legítimos cadastrados no meio do
  ano. Os primeiros pagamentos deles aparecem no topo do ranking quando o valor também é
  alto.
- **Notas de mesmo valor podem trocar de dono.** Quando um fornecedor tem várias notas
  abertas com valores quase iguais, um pagamento com tarifa ou atraso pode casar com a
  nota de outro pagamento. Esses casos são raros (0–2 por seed) e costumam sair como
  `sugerida`.
- **Análise em lote.** As médias e os ciclos de cada fornecedor usam o ano inteiro, menos
  o próprio pagamento avaliado. Num uso em produção, o histórico deveria olhar só para
  trás.
- **Dados sintéticos.** O realismo vem dos padrões, não de empresas reais. Os números
  acima medem o sistema contra o próprio gerador e servem para comparar versões, não para
  prometer desempenho em dados reais.
- **O score não é recalculado depois de uma revisão.** O ranking é calculado em lote, na
  execução do pipeline. Quando um analista aprova ou rejeita uma sugestão, o status muda,
  mas a posição no ranking e os motivos continuam os da última execução.
- **Bancos criados antes das migrações precisam ser recriados.** O esquema agora evolui por
  migrações (Alembic), aplicadas na subida. Um banco criado pela versão anterior, sem
  histórico de migrações, é recusado com instruções; com Docker, `docker compose down -v`.
- **Sem autenticação.** Qualquer pessoa com acesso à página pode aprovar ou rejeitar
  sugestões. O campo `decided_by` registra apenas "analista", sem identificar a pessoa.

## Estrutura

```
backend/
  src/bankrecon/
    generator/        perfis, notas, extrato com ruído, anomalias e gabarito
    reconciliation/   resolução de fornecedor e as três camadas
    anomalies/        features, Isolation Forest e motivos
    evaluation/       métricas contra o gabarito e tabelas em Markdown
    db/               modelos SQLAlchemy, carga do banco, consultas e revisões
    api/              aplicação FastAPI (o ML roda como módulo, não como serviço)
    results.py        persistência dos resultados com impressão digital das entradas
    cli.py            generate, reconcile, detect, evaluate, load-db e demo
  tests/              testes unitários, de API e de ponta a ponta
frontend/
  src/lib/            cliente tipado da API, formatação e hooks de dados
  src/components/     totais, filtros, tabela e painel lateral (com testes)
docker-compose.yml    Postgres, API e página
```

## Desenvolvimento

```bash
cd backend
pytest --cov=bankrecon
ruff check . && ruff format --check .

cd ../frontend
npm test && npm run lint && npm run typecheck
```

O GitHub Actions roda o lint e os testes do backend e do frontend, faz o build da página
e sobe o `docker compose` para conferir que a página responde através da API.

## Status

- [x] Etapa 1: gerador e gabarito
- [x] Etapa 2: conciliação em camadas, com acerto medido
- [x] Etapa 3: anomalias com score em ranking e motivos, com recall por tipo medido
- [x] Etapa 4: API em FastAPI, Postgres, página em Next.js e Docker Compose
- [ ] Etapa 5: GIF da demo

Depois do MVP: comparar o Isolation Forest com o LOF usando o mesmo gabarito.
