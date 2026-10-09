"""Bulk-approve imported PENDING sources through the SAME admin review endpoint the API uses.

Run this after:  python ingest_schemes.py data/schemes_final.csv --no-embeddings
It logs in as the admin account, then approves every pending source whose CSV row has an acceptable
"Match Quality" (default: EXACT only). Everything else stays PENDING for manual review.

Usage:
    python bulk_verify.py data/schemes_final.csv
    python bulk_verify.py data/schemes_final.csv --quality EXACT SIMILAR
    python bulk_verify.py data/schemes_final.csv --embed      # also build embeddings afterwards (resumable)
"""
import argparse
import csv
import time

from app import create_app
from config import Config
from database.db import db
from database.models import DocumentChunk, GovernmentDocument, SchemeSource


def embed_batch(llm, texts, model):
    """One embeddings call that tolerates providers (e.g. Gemini) leaving `index` empty, and retries on rate limits."""
    for attempt in range(6):
        try:
            data = list(llm.embeddings.create(model=model, input=texts).data)
            if all(item.index is not None for item in data):
                data.sort(key=lambda item: item.index)
            return [item.embedding for item in data]
        except Exception as exc:
            wait = 20 * (attempt + 1)
            print(f"  embedding call failed ({type(exc).__name__}: {str(exc)[:120]}), retrying in {wait}s")
            time.sleep(wait)
    raise RuntimeError("Embedding API keeps failing. Re-run later; it resumes where it stopped.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="?", help="Only needed to filter by Match Quality")
    parser.add_argument("--all", action="store_true", help="Approve EVERY pending source (no CSV needed)")
    parser.add_argument("--quality", nargs="+", default=["EXACT"], help="Match Quality values to approve")
    parser.add_argument("--embed", action="store_true", help="Create embeddings for verified chunks in batches")
    parser.add_argument("--max-chunks", type=int, default=0, help="Embed at most this many chunks per run (0 = all)")
    args = parser.parse_args()
    wanted = {q.upper() for q in args.quality}
    if args.all:
        wanted = {"ALL"}
    elif not args.csv:
        parser.error("Give the CSV path, or use --all")

    urls = None
    if not args.all:
        with open(args.csv, encoding="utf-8-sig", newline="") as stream:
            urls = {row["Source URL"].strip() for row in csv.DictReader(stream)
                    if row.get("Match Quality", "").strip().upper() in wanted}
        print(f"{len(urls)} source URLs have Match Quality in {sorted(wanted)}")

    app = create_app()
    with app.app_context():
        pending = [s.id for s in SchemeSource.query.filter_by(status="PENDING").order_by(SchemeSource.id).all()
                   if urls is None or s.source_url in urls]
        db.session.close()
        print(f"{len(pending)} pending sources will be approved")

        client = app.test_client()
        login = client.post("/api/login", json={"username": Config.DEMO_ADMIN_USERNAME,
                                                "password": Config.DEMO_ADMIN_PASSWORD})
        if login.status_code != 200:
            parser.error("Admin login failed. Run init_db.py and check DEMO_ADMIN_PASSWORD in .env")

        ok = failed = 0
        for number, source_id in enumerate(pending, 1):
            response = client.post(f"/api/admin/sources/{source_id}/review", json={
                "status": "VERIFIED",
                "review_notes": "Bulk-approved: source URL matched with Match Quality " + "/".join(sorted(wanted)),
            })
            if response.status_code == 200:
                ok += 1
            else:
                failed += 1
                print(f"  source {source_id} failed: {response.status_code} {response.get_data(as_text=True)[:150]}")
            if number % 200 == 0:
                print(f"  {number}/{len(pending)} done")
        print(f"Approved {ok}, failed {failed}")

        if args.embed:
            if not Config.OPENAI_API_KEY:
                parser.error("OPENAI_API_KEY is not set, cannot create embeddings")
            from agent.llm import make_client
            llm = make_client(Config.OPENAI_API_KEY)
            chunks = [c for c in DocumentChunk.query.join(GovernmentDocument)
                      .filter(GovernmentDocument.verification_status == "VERIFIED",
                              GovernmentDocument.is_current.is_(True)).all() if not c.embedding]
            print(f"{len(chunks)} chunks need embeddings")
            if args.max_chunks:
                chunks = chunks[:args.max_chunks]
            for start in range(0, len(chunks), 50):
                batch = chunks[start:start + 50]
                vectors = embed_batch(llm, [c.text for c in batch], Config.EMBEDDING_MODEL)
                for chunk, vector in zip(batch, vectors):
                    chunk.embedding = vector
                db.session.commit()
                print(f"  embedded {min(start + 50, len(chunks))}/{len(chunks)}")


if __name__ == "__main__":
    main()