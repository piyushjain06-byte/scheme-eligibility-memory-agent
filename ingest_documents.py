"""Extract a local PDF/TXT/Markdown file and add it to a scheme's document memory."""
import argparse
from pathlib import Path

from app import create_app
from config import Config
from database.db import db
from database.models import Scheme
from agent.rag import ingest_document


def extract(path: Path) -> str:
    if path.suffix.lower() in {".txt", ".md"}:
        return path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    raise ValueError("Supported document formats are .txt, .md, and .pdf")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", help="Local PDF, TXT, or Markdown document")
    parser.add_argument("--scheme-id", type=int, required=True)
    parser.add_argument("--source-url", help="Source URL retained for later review/citation")
    parser.add_argument("--source-type", default="OFFICIAL_DOCUMENT")
    parser.add_argument("--no-embeddings", action="store_true")
    args = parser.parse_args()
    app = create_app()
    client = None
    if not args.no_embeddings and Config.OPENAI_API_KEY:
        from openai import OpenAI
        client = OpenAI(api_key=Config.OPENAI_API_KEY)
    elif not args.no_embeddings:
        parser.error("Set OPENAI_API_KEY for semantic embeddings, or pass --no-embeddings")
    with app.app_context():
        from upgrade_db import upgrade_existing_schema
        upgrade_existing_schema()
        scheme = db.session.get(Scheme, args.scheme_id)
        if scheme is None:
            parser.error(f"Unknown scheme id: {args.scheme_id}")
        path = Path(args.document)
        doc = ingest_document(scheme, title=path.name, content=extract(path),
            source_url=args.source_url, source_type=args.source_type, client=client,
            embedding_model=Config.EMBEDDING_MODEL)
        db.session.commit()
        print(f"Indexed document {doc.id} for {scheme.name} ({len(doc.chunks)} chunks).")
        if scheme.is_demo or not scheme.source_verified:
            print("Document remains non-verified and will not be used for public government answers.")


if __name__ == "__main__":
    main()
