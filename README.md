# ColetaCarbono

API (FastAPI + SQLAlchemy + SQLite) para cadastro de empresas recicladoras,
registro de volumes coletados e validação pela prefeitura, com cálculo do
carbono evitado e da estimativa financeira.

## Como rodar

```bash
cp .env.example .env   # ajuste SECRET_KEY e, se quiser, o SMTP
uv sync
uv run python main.py  # http://127.0.0.1:8000/docs
```

Na inicialização, `src/create_db.sql` cria as tabelas e, com
`SEED_DEV_DATA=true`, `src/seed_dev.sql` cadastra prefeituras, materiais e
contas de demonstração.

> O script usa `CREATE TABLE IF NOT EXISTS`, que não altera tabelas já
> existentes. Se o schema mudar, apague o `carbono.db` para recriá-lo
> (a aplicação avisa na inicialização quando detecta colunas ausentes).

## Variáveis de ambiente

Veja [`.env.example`](.env.example). As principais:

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `SECRET_KEY` | chave de desenvolvimento | Assinatura dos tokens JWT. **Obrigatória em produção.** |
| `DATABASE_URL` | `sqlite:///./carbono.db` | Banco de dados. |
| `SEED_DEV_DATA` | `true` | Popula o banco com dados de demonstração. |
| `CORS_ORIGINS` | `*` | Origens permitidas, separadas por vírgula. |
| `PUBLIC_API_URL` | `http://localhost:8000` | Base dos links enviados por e-mail. |
| `SMTP_HOST` | vazio | Sem ele, os e-mails só aparecem no log. |

## Desenvolvimento

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```
