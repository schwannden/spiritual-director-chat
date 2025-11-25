# Spiritual Direction Chat

A small FastAPI + Chroma + LM Studio stack that chats like a gentle spiritual director using passages from *On Living Well* and *Imitatio Christi*. The project mirrors the workflow described in `docs/blog-tech.md` and is ready to run locally via Docker Compose.

## Quick start
1. **Install** Docker + Docker Compose and LM Studio (start its local API on port `1234` with `openai/gpt-oss-20b` or another chat-capable model).
2. **Configure env vars**:
   ```bash
   cp .env.example .env
   # Fill CHROMA_API_KEY, CHROMA_TENANT, and optionally tweak LM_STUDIO_BASE_URL/LM_STUDIO_CHAT_MODEL
   ```
   When running the API in Docker while LM Studio stays on your host, keep `LM_STUDIO_BASE_URL=http://host.docker.internal:1234`.
3. **Build the image**:
   ```bash
   docker compose build
   ```
4. **Upload the chapters to Chroma** (one-time or whenever content changes):
   ```bash
   # All collections
   docker compose run --rm api python main.py

   # Single collection
   docker compose run --rm api python main.py --collections imitatio-christi
   ```
5. **Run the API**:
   ```bash
   docker compose up
   ```
   Open `http://localhost:8000/chat` for the UI. `GET /health` reports Chroma and LM Studio status.

## Local dev without Docker
```bash
uv sync                    # creates .venv and installs deps from pyproject/uv.lock
source .venv/bin/activate  # optional; `uv run` activates automatically
cp .env.example .env       # populate keys
uv run python main.py      # upload documents
uv run uvicorn app:app --reload

## Development tooling
- Install dev dependencies and Git hooks: `uv sync && uv run pre-commit install`
- Run the full suite locally: `uv run pre-commit run --all-files`
```

## Project layout
- `app.py` – FastAPI app, LM Studio chat integration, and retrieval logic.
- `main.py` – CLI uploader that writes Markdown chapters into Chroma collections.
- `static/chat.html` – Tailwind-based chat UI served at `/chat`.
- `on-living-well/` and `imitatio-christi/` – Chapter-level Markdown content for ingestion.
- `docs/blog-tech.md` – Narrative on how the system was built.

## Notes
- Dependencies are managed with `uv`; use `uv sync` and `uv run ...` for local workflows.
- No secrets are committed. Use `.env` for API keys/tenants; `.gitignore` keeps it out of Git.
- The default LM Studio base URL points at `host.docker.internal` so the container can hit the host API. On Linux, ensure the `extra_hosts` entry in `docker-compose.yml` works for your Docker runtime or replace the URL with your host IP.
- Adjust retrieval depth via the `top_k` request body field; the server caps it to avoid over-fetching.
