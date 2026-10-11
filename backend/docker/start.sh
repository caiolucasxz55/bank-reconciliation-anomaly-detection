#!/bin/sh
# Container entrypoint: optionally load demo data, then serve the API.
# Database migrations run when the API starts (FastAPI lifespan).
set -eu

case "$(printf '%s' "${LOAD_DEMO_DATA:-false}" | tr '[:upper:]' '[:lower:]')" in
  true | 1 | yes | sim)
    # Idempotent: only generates and loads data when the database is empty.
    bankrecon demo --data "${BANKRECON_DATA_DIR:-/app/data}"
    ;;
  false | 0 | no | nao | "") ;;
  *)
    echo "aviso: LOAD_DEMO_DATA='${LOAD_DEMO_DATA}' não reconhecido; use true ou false" >&2
    ;;
esac

exec uvicorn --factory bankrecon.api.app:create_app --host 0.0.0.0 --port 8000
