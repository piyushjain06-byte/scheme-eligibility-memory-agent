"""Import and index a scheme JSON or CSV file; run after initializing the database."""
import argparse
from app import create_app
from config import Config
from agent.ingestion import ingest_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", help="Path to a JSON or CSV scheme dataset")
    parser.add_argument("--no-embeddings", action="store_true", help="Build chunks and lexical index without API embeddings")
    args = parser.parse_args()
    app = create_app()
    client = None
    if not args.no_embeddings and Config.OPENAI_API_KEY:
        from agent.llm import make_client
        client = make_client(Config.OPENAI_API_KEY)
    elif not args.no_embeddings:
        parser.error("Set OPENAI_API_KEY for semantic embeddings, or pass --no-embeddings")
    with app.app_context():
        from upgrade_db import upgrade_existing_schema
        upgrade_existing_schema()
        result = ingest_file(args.dataset, embedding_client=client, embedding_model=Config.EMBEDDING_MODEL)
        print(f"Imported {result['total']} scheme(s): {result['created']} created, {result['updated']} updated.")
        if client is None:
            print("Chunks are indexed for lexical retrieval. Add OPENAI_API_KEY and re-run to create semantic embeddings.")


if __name__ == "__main__":
    main()
