# Frontend

Página única em Next.js com:

- os totais no topo (conciliadas, sugeridas, divergentes e alto risco), que também
  funcionam como filtro;
- a lista de transações, com filtros por status e por score, busca e ordenação;
- um painel lateral com os motivos do score, as notas casadas e os botões de aprovar ou
  rejeitar uma sugestão.

O navegador chama `/api/*` no próprio Next, e o route handler `src/app/api/[...path]`
repassa essas chamadas para a API FastAPI em `API_URL` (padrão `http://localhost:8000`).
A variável é lida a cada requisição, então a mesma imagem funciona com qualquer endereço.

```bash
npm install
npm run dev          # http://localhost:3000 (com a API rodando em :8000)
npm test             # vitest
npm run lint && npm run typecheck
```
