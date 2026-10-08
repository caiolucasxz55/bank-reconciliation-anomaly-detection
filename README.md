# Bank Reconciliation & Anomaly Detection

Plataforma que concilia extratos bancários com notas fiscais e aponta transações incomuns
para investigação humana.

> Em construção. Veja a seção de status abaixo.

## Desenvolvimento

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
```
