"""CLI: rebuild the DKORWORLD2 FAISS index from data/faqs.json."""
from __future__ import annotations

from .rag_index import DATA_PATH, EMBEDDING_MODEL, INDEX_PATH, META_PATH, build_index


def main() -> None:
    index, metadata = build_index()
    print(f"DATA: {DATA_PATH}")
    print(f"EMBEDDING_MODEL: {EMBEDDING_MODEL}")
    print(f"ITEMS: {len(metadata)}")
    print(f"DIM: {index.d}")
    print(f"INDEX: {INDEX_PATH}")
    print(f"META: {META_PATH}")


if __name__ == "__main__":
    main()
