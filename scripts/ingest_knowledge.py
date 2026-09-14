"""Build the persistent Chroma knowledge collection."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from app.rag.ingest import load_knowledge_documents
from app.rag.retriever import build_vector_store

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Index Markdown knowledge documents into Chroma")
    parser.add_argument("--input", type=Path, default=Path(os.getenv("KNOWLEDGE_BASE_PATH", "data/knowledge/")))
    parser.add_argument("--persist", type=Path, default=Path(os.getenv("CHROMA_PERSIST_DIRECTORY", "data/chroma/")))
    parser.add_argument("--collection", default="customer_service_knowledge")
    parser.add_argument("--max-chars", type=int, default=450)
    parser.add_argument("--overlap", type=int, default=50)
    parser.add_argument("--recreate", action="store_true", help="Recreate the collection before indexing")
    args = parser.parse_args()

    documents = load_knowledge_documents(args.input, max_chars=args.max_chars, overlap=args.overlap)
    build_vector_store(
        documents,
        persist_directory=args.persist,
        collection_name=args.collection,
        recreate=args.recreate,
    )
    print(f"Indexed {len(documents)} chunks into '{args.collection}'.")


if __name__ == "__main__":
    main()
