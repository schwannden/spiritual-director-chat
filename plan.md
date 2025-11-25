# RAG Spiritual Director Chat – Design Plan

## 0. Goal & Scope
- Build a local browser-based chat that speaks with the tone of the book content while grounded in retrieved passages.
- Use LM Studio for chat completions; rely on Chroma Cloud’s managed embedding pipeline for retrieval.
- Use the existing Chroma Cloud collection `on-living-well` as the retrieval backend.

---

## 1. Enrich Chroma Collection With Embeddings
### Objectives
- Ensure every Markdown document in `on-living-well/` has an embedding stored in Chroma so queries can be matched semantically.

### Tasks
1. Extend `main.py`:
   - Load Markdown files, gather ids/documents/metadatas.
   - Call `collection.upsert(...)` without supplying embeddings so the managed Chroma collection applies its built-in embedder automatically.
   - Consider chunking long documents (optional for v1; if a file exceeds the chosen context length, split it into smaller pieces and suffix ids accordingly).
2. Run `python main.py` after the update to refresh the collection.
3. Validate by running a temporary query (via REPL or script) that the collection now has embeddings (`collection.count()` and a sample `collection.get(ids=[...], include=["embeddings"])`).

### Notes
- No dependency on LM Studio for embeddings keeps the collection aligned with the managed service’s expected dimensionality.
- If chunking is added later, keep `ids` stable (e.g., `chapter-01#chunk-1`) so re-ingestion overwrites consistently.

---

## 2. RAG API Service
### Objectives
- Expose a local HTTP API that orchestrates retrieval plus generation for the chat UI.

### Architecture
- Use FastAPI (preferred for async support and easy JSON schemas) served by Uvicorn.
- Keep a single Chroma client/collection instance loaded at startup.
- Store an in-memory map of conversations if session management is desired (optional for v1).

### Endpoints
1. `POST /chat`
   - Request payload: `{ "messages": [{ "role": "system"|"user"|"assistant", "content": "<text>" }], "top_k": 3 (optional) }`.
   - Steps:
     - Extract the latest user message; if missing, return 400.
     - Run `collection.query` with `query_texts=[latest_user]`, letting Chroma handle embedding, and request `include=["documents","metadatas","distances"]`.
     - Format the retrieved passages into a context string with simple citations (e.g., “From filename: content”).
     - Build the prompt:
       - fixed system message: “You are a gentle spiritual director grounded in the retrieved passages…”
       - extra “assistant” message that includes the context block.
       - append prior user/assistant turns from the request.
     - Call LM Studio `/v1/chat/completions` with the assembled messages, passing temperature and max_tokens defaults.
     - Return `{ "reply": "<assistant text>", "sources": [...] }` where sources hold filenames/distances.
2. `GET /health`
   - Returns basic status confirming Chroma and LM Studio connectivity; useful for frontend to check readiness.

### Implementation Details
- Keep LM Studio base URL in an env var (`LM_STUDIO_BASE_URL=http://localhost:1234`).
- Wrap outbound calls with timeout + error translation for readable client errors.
- For logging, print the top retrieved filenames and distances to aid debugging (omit actual text in logs).

---

## 3. Browser Chat UI
### Objectives
- Provide a minimal Tailwind-styled chat page served by the API to interact with `POST /chat`.

### Structure
1. Deliver `chat.html` from a `templates/` or `static/` directory via FastAPI’s `StaticFiles`.
2. Use Tailwind via CDN (`<script src="https://cdn.tailwindcss.com"></script>`).
3. Layout:
   - Full-height flex column.
   - Scrollable message area with alternating bubble styles for user vs. director.
   - Fixed footer input form with textarea, send button, and optional “Enter to send” toggle.
4. JavaScript:
   - Maintain an array of message objects `{ role, content }`.
   - On send:
     - push the user message into the transcript.
     - POST to `/chat` with current `messages`.
     - Show a loading indicator while awaiting response.
     - Append the assistant reply and list the cited sources (e.g., hyperlink or tooltip with filenames).
   - Handle errors by displaying a friendly alert area.

### Enhancements (Later)
- Streaming updates via `ReadableStream` if LM Studio supports streaming.
- Conversation persistence by storing `messages` in `localStorage`.

---

## 4. Local Run & Dev Workflow
1. Install dependencies with `uv sync` (uses `pyproject.toml` + `uv.lock`).
2. Start LM Studio with both embedding and chat models available.
3. Run `uv run python main.py` to ensure embeddings are up-to-date.
4. Launch the API server: `uv run uvicorn app:app --reload`.
5. Open `http://localhost:8000/chat.html` (or the served route) in a browser and begin chatting.
6. Iterate: monitor console logs for retrieval quality, adjust chunking/top_k/system prompt as needed.

---

## 5. Future Considerations
- Add guardrails (e.g., refuse to answer outside scope).
- Implement evaluation scripts comparing retrieval rankings.
- Support multi-turn memory trimming to stay within model context limits.
