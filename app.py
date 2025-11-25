from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Literal, Sequence

import chromadb
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from chromadb.config import Settings

load_dotenv()


def required_env(name: str, default: str | None = None) -> str:
  value = os.environ.get(name, default)
  if value:
    return value
  raise RuntimeError(f"Environment variable {name} is required for the API to start.")


CHROMA_API_KEY = required_env("CHROMA_API_KEY")
CHROMA_TENANT = required_env("CHROMA_TENANT")
CHROMA_DATABASE = required_env("CHROMA_DATABASE", "dev")
LM_STUDIO_BASE_URL = os.environ.get("LM_STUDIO_BASE_URL", "http://host.docker.internal:1234")
LM_STUDIO_CHAT_MODEL = os.environ.get("LM_STUDIO_CHAT_MODEL", "openai/gpt-oss-20b")

MAX_CONTEXT_CHARS_PER_DOC = 1200
DEFAULT_TOP_K = 7
MAX_TOP_K = 8
REQUEST_TIMEOUT_SECONDS = 60.0
RESPONSE_LENGTH_CONFIG = {
  "short": {"approx_chars": 500},
  "medium": {"approx_chars": 800},
  "long": {"approx_chars": 1200},
}

def build_chroma_client() -> chromadb.ClientAPI:
  # Force the Cloud client to use the v2 REST path over HTTPS.
  return chromadb.CloudClient(
    api_key=CHROMA_API_KEY,
    tenant=CHROMA_TENANT,
    database=CHROMA_DATABASE,
  )


client = build_chroma_client()
COLLECTION_KEYS_ORDER = ["on-living-well", "imitatio-christi"]
COLLECTION_DISPLAY_NAMES = {
  "on-living-well": "On Living Well",
  "imitatio-christi": "Imitatio Christi",
}
DEFAULT_COLLECTION_KEYS = ["on-living-well"]

COLLECTIONS = {
  "on-living-well": client.get_or_create_collection(name="on-living-well"),
  "imitatio-christi": client.get_or_create_collection(name="imitatio-christi"),
}

app = FastAPI(title="Spiritual Director Chat API")
app.add_middleware(
  CORSMiddleware,
  allow_origins=["*"],
  allow_credentials=True,
  allow_methods=["*"],
  allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

if STATIC_DIR.exists():
  app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

CHAT_HTML_PATH = STATIC_DIR / "chat.html"


class Message(BaseModel):
  role: Literal["system", "user", "assistant"]
  content: str


class ChatRequest(BaseModel):
  messages: list[Message] = Field(default_factory=list)
  top_k: int = Field(default=DEFAULT_TOP_K, ge=1)
  collections: list[str] | None = None
  response_length: Literal["short", "medium", "long"] = Field(default="medium")


class Source(BaseModel):
  collection: str
  collection_label: str
  filename: str
  distance: float | None = None


class ChatResponse(BaseModel):
  reply: str
  sources: list[Source] = Field(default_factory=list)


async def get_http_client() -> httpx.AsyncClient:
  http_client: httpx.AsyncClient | None = getattr(app.state, "http_client", None)
  if http_client is None:
    http_client = httpx.AsyncClient(
      base_url=LM_STUDIO_BASE_URL,
      timeout=REQUEST_TIMEOUT_SECONDS,
    )
    app.state.http_client = http_client
  return http_client


def latest_user_message(messages: Iterable[Message]) -> str | None:
  for message in reversed(list(messages)):
    if message.role == "user":
      content = message.content.strip()
      if content:
        return content
  return None


def normalize_collection_keys(selected: Sequence[str] | None) -> list[str]:
  if not selected:
    return DEFAULT_COLLECTION_KEYS.copy()

  normalized: list[str] = []

  for raw in selected:
    if not raw:
      continue
    key = raw.strip().lower()
    if key == "both":
      return COLLECTION_KEYS_ORDER.copy()
    if key in COLLECTIONS:
      normalized.append(key)
    else:
      raise HTTPException(status_code=400, detail=f"Unknown collection: {raw}")

  if not normalized:
    return DEFAULT_COLLECTION_KEYS.copy()

  seen: set[str] = set()
  unique_keys: list[str] = []
  for key in normalized:
    if key not in seen:
      unique_keys.append(key)
      seen.add(key)

  return unique_keys


def voice_for_collections(collection_keys: Sequence[str]) -> str:
  if set(collection_keys) == {"on-living-well", "imitatio-christi"}:
    return (
      "Blend the warmth and pastoral cadence of Eugene Peterson with the "
      "devotional humility of Thomas à Kempis."
    )
  if collection_keys == ["on-living-well"]:
    return "Write with the conversational, pastoral voice of Eugene Peterson."
  if collection_keys == ["imitatio-christi"]:
    return "Write with the reflective, devotional tone of Thomas à Kempis."
  return "Respond as a gentle spiritual director with warmth and clarity."


def per_collection_top_k(collection_keys: Sequence[str], top_k: int) -> dict[str, int]:
  keys = list(collection_keys)
  if not keys:
    raise HTTPException(status_code=400, detail="At least one collection must be selected.")

  if len(keys) == 1:
    key = keys[0]
    return {key: min(max(top_k, 1), MAX_TOP_K)}

  if len(keys) == 2:
    allocation = {key: min(4, MAX_TOP_K) for key in keys}
    return allocation

  base = max(top_k, len(keys))
  per_key = max(base // len(keys), 1)
  allocation = {key: min(per_key, MAX_TOP_K) for key in keys}

  remainder = base - per_key * len(keys)
  index = 0
  while remainder > 0:
    key = keys[index % len(keys)]
    if allocation[key] < MAX_TOP_K:
      allocation[key] += 1
      remainder -= 1
    index += 1
    if index > len(keys) * 4:
      break

  return allocation


def query_collections(query_text: str, collection_keys: Sequence[str], top_k: int) -> list[dict[str, Any]]:
  hits: list[dict[str, Any]] = []

  allocation = per_collection_top_k(collection_keys, top_k)

  for key, per_top_k in allocation.items():
    collection = COLLECTIONS[key]
    result = collection.query(
      query_texts=[query_text],
      n_results=per_top_k,
      include=["documents", "metadatas", "distances"],
    )

    documents = (result.get("documents") or [[]])[0] or []
    metadatas = (result.get("metadatas") or [[]])[0] or []
    distances = (result.get("distances") or [[]])[0] or []

    for document, metadata, distance in zip(documents, metadatas, distances):
      hits.append(
        {
          "collection": key,
          "document": document,
          "metadata": metadata or {},
          "distance": distance,
        }
      )

  hits.sort(
    key=lambda item: item["distance"]
    if isinstance(item.get("distance"), (int, float))
    else float("inf")
  )

  return hits[:top_k]


def build_context(
  hits: Sequence[dict[str, Any]],
) -> tuple[str, list[Source]]:
  context_chunks: list[str] = []
  sources: list[Source] = []

  for item in hits:
    document = (item.get("document") or "").strip()
    if not document:
      continue

    snippet = document
    if len(snippet) > MAX_CONTEXT_CHARS_PER_DOC:
      snippet = f"{snippet[:MAX_CONTEXT_CHARS_PER_DOC]}..."

    metadata = item.get("metadata") or {}
    filename = metadata.get("filename") or "unknown"

    collection_key = item.get("collection") or "unknown"
    collection_label = COLLECTION_DISPLAY_NAMES.get(collection_key, collection_key)

    context_chunks.append(f"[{collection_label} · {filename}] {snippet}")
    sources.append(
      Source(
        collection=collection_key,
        collection_label=collection_label,
        filename=filename,
        distance=item.get("distance"),
      )
    )

  context_text = "\n\n".join(context_chunks)
  return context_text, sources


def build_messages(
  context: str,
  conversation: list[Message],
  latest_user: str | None = None,
  collection_keys: Sequence[str] | None = None,
  response_length: Literal["short", "medium", "long"] = "medium",
  target_language: str | None = None,
) -> list[dict[str, str]]:
  voice = voice_for_collections(collection_keys or [])
  language_instruction = (
    f"Always answer in {target_language}."
    if target_language
    else "Always answer in the same language as the most recent user message."
  )
  system_prompt = (
    "You are a gentle spiritual director. "
    f"{voice} "
    "Give fluent, natural responses that feel personal and prayerful, not like database output. "
    "Draw primarily from the provided context passages when available. "
    f"{language_instruction}"
  )

  messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]

  if context:
    messages.append(
      {
        "role": "system",
        "content": (
          "Use the following excerpts from the book as primary reference material. "
          "If they do not address the user question, say so briefly and offer a reflective "
          "response grounded in your role as a spiritual director.\n\n"
          f"{context}"
        ),
      }
    )

  if latest_user:
    messages.append(
      {
        "role": "system",
        "content": (
          "Use the language of the latest user message shown below for your reply. "
          f"Latest user message: {latest_user}"
        ),
      }
    )

  length_config = RESPONSE_LENGTH_CONFIG.get(response_length, RESPONSE_LENGTH_CONFIG["medium"])
  approx_chars = length_config["approx_chars"]
  messages.append(
    {
      "role": "system",
      "content": (
        f"Keep the reply focused and around {approx_chars} characters. "
        "Prioritize one or two clear insights, avoid repetition, and stop when the main idea is delivered."
      ),
    }
  )

  for message in conversation:
    if message.role in ("user", "assistant"):
      messages.append({"role": message.role, "content": message.content})

  return messages


def strip_code_fences(text: str) -> str:
  cleaned = text.strip()
  if cleaned.startswith("```"):
    parts = cleaned.split("\n", 1)
    if len(parts) == 2:
      cleaned = parts[1]
    if cleaned.endswith("```"):
      cleaned = cleaned.rsplit("```", 1)[0]
  return cleaned.strip()


async def translate_query(http_client: httpx.AsyncClient, text: str) -> dict[str, str] | None:
  messages = [
    {
      "role": "system",
      "content": (
        "Detect the input language and translate it to English for retrieval. "
        "Return ONLY compact JSON with fields 'language' and 'translation'."
      ),
    },
    {"role": "user", "content": text},
  ]

  try:
    response = await http_client.post(
      "/v1/chat/completions",
      json={
        "model": LM_STUDIO_CHAT_MODEL,
        "messages": messages,
        "temperature": 0.0,
      },
    )
  except httpx.HTTPError:
    return None

  if response.status_code >= 400:
    return None

  payload = response.json()
  try:
    raw = payload["choices"][0]["message"]["content"]
  except (KeyError, IndexError, TypeError):
    return None

  cleaned = strip_code_fences(str(raw))
  try:
    data = json.loads(cleaned)
  except json.JSONDecodeError:
    return None

  language = str(data.get("language") or "").strip() or None
  translation = str(data.get("translation") or "").strip() or None
  if not translation:
    return None

  return {"language": language or None, "translation": translation}


def is_chinese_language(language: str | None) -> bool:
  if not language:
    return False
  normalized = language.strip().lower()
  return "chinese" in normalized or normalized.startswith("zh")


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
  if not request.messages:
    raise HTTPException(status_code=400, detail="Conversation history is required.")

  latest_user = latest_user_message(request.messages)
  if not latest_user:
    raise HTTPException(status_code=400, detail="No user message provided.")

  top_k = min(request.top_k, MAX_TOP_K)

  collection_keys = normalize_collection_keys(request.collections)
  http_client = await get_http_client()

  translation = await translate_query(http_client, latest_user)
  query_text = translation.get("translation") if translation else latest_user
  detected_language = translation.get("language") if translation else None
  target_language = "Traditional Chinese" if is_chinese_language(detected_language) else detected_language

  hits = query_collections(query_text, collection_keys, top_k)
  context_text, sources = build_context(hits)
  messages = build_messages(
    context_text,
    request.messages,
    latest_user,
    collection_keys,
    request.response_length,
    target_language,
  )

  try:
    response = await http_client.post(
      "/v1/chat/completions",
      json={
        "model": LM_STUDIO_CHAT_MODEL,
        "messages": messages,
        "temperature": 0.7,
      },
    )
  except httpx.HTTPError as exc:
    raise HTTPException(
      status_code=502,
      detail=f"Cannot reach LM Studio at {LM_STUDIO_BASE_URL}: {exc}",
    ) from exc

  if response.status_code >= 400:
    raise HTTPException(
      status_code=502,
      detail=f"LM Studio request failed: {response.text}",
    )

  payload = response.json()
  try:
    reply = payload["choices"][0]["message"]["content"].strip()
  except (KeyError, IndexError, AttributeError) as exc:
    raise HTTPException(status_code=502, detail="Malformed response from LM Studio.") from exc

  return ChatResponse(reply=reply, sources=sources)


@app.get("/chat")
async def chat_page() -> FileResponse:
  if not CHAT_HTML_PATH.exists():
    raise HTTPException(status_code=404, detail="Chat UI not found.")
  return FileResponse(path=str(CHAT_HTML_PATH))


@app.get("/health")
async def health() -> dict[str, Any]:
  status: dict[str, Any] = {"status": "ok"}

  collection_counts: dict[str, Any] = {}
  for key in COLLECTION_KEYS_ORDER:
    label = COLLECTION_DISPLAY_NAMES.get(key, key)
    try:
      collection_counts[label] = COLLECTIONS[key].count()
    except Exception as exc:  # pragma: no cover - defensive logging
      status["status"] = "error"
      collection_counts[label] = f"error: {exc}"

  status["collections"] = collection_counts

  http_client = await get_http_client()
  try:
    response = await http_client.get("/v1/models")
    status["lm_studio"] = response.status_code
  except httpx.HTTPError as exc:  # pragma: no cover
    status["status"] = "error"
    status["lm_studio_error"] = str(exc)

  return status


@app.on_event("shutdown")
async def shutdown_event() -> None:
  http_client: httpx.AsyncClient | None = getattr(app.state, "http_client", None)
  if http_client is not None:
    await http_client.aclose()
