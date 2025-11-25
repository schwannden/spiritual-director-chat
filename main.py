from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Iterable

import chromadb
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

COLLECTION_SOURCES = {
  "on-living-well": BASE_DIR / "on-living-well",
  "imitatio-christi": BASE_DIR / "imitatio-christi",
}


def required_env(name: str, default: str | None = None) -> str:
  value = os.environ.get(name, default)
  if value:
    return value
  raise RuntimeError(f"Environment variable {name} is required to upload documents.")


def build_client() -> chromadb.ClientAPI:
  api_key = required_env("CHROMA_API_KEY")
  tenant = required_env("CHROMA_TENANT")
  database = required_env("CHROMA_DATABASE", "dev")
  return chromadb.CloudClient(
    api_key=api_key,
    tenant=tenant,
    database=database,
  )


def load_markdown_documents(source_dir: Path) -> tuple[list[str], list[str], list[dict]]:
  if not source_dir.exists():
    raise FileNotFoundError(f"Source directory not found: {source_dir}")

  documents: list[str] = []
  ids: list[str] = []
  metadatas: list[dict] = []

  for path in sorted(source_dir.glob("*.md")):
    text = path.read_text(encoding="utf-8").strip()
    if not text:
      continue
    ids.append(path.stem)
    documents.append(text)
    metadatas.append({"filename": path.name})

  return ids, documents, metadatas


def upload_collection(client: chromadb.ClientAPI, collection_name: str, paths: Iterable[Path]) -> int:
  paths = list(paths)
  if not paths:
    raise ValueError("At least one source directory is required.")

  ids: list[str] = []
  documents: list[str] = []
  metadatas: list[dict] = []

  for path in paths:
    loaded_ids, loaded_documents, loaded_metadatas = load_markdown_documents(path)
    ids.extend(loaded_ids)
    documents.extend(loaded_documents)
    metadatas.extend(loaded_metadatas)

  if not ids:
    return 0

  collection = client.get_or_create_collection(name=collection_name)
  collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
  return len(ids)


def ingest(selected: list[str] | None = None) -> None:
  target_keys = selected or list(COLLECTION_SOURCES.keys())
  client = build_client()

  for key in target_keys:
    source_dir = COLLECTION_SOURCES.get(key)
    if not source_dir:
      print(f"Skipping unknown collection key: {key}")
      continue
    count = upload_collection(client, key, [source_dir])
    print(f"Uploaded {count} documents to collection '{key}'.")


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Upload Markdown documents into Chroma collections.")
  parser.add_argument(
    "--collections",
    nargs="+",
    default=[],
    help="Collection keys to upload (default: all).",
  )
  return parser.parse_args()


if __name__ == "__main__":
  args = parse_args()
  ingest(args.collections)
