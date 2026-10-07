"""Local document memory with optional OpenAI embeddings and cosine retrieval."""
from __future__ import annotations

import hashlib
import math
import re

from database.db import db
from database.models import DocumentChunk, GovernmentDocument, Scheme, SchemeSource


def searchable_scheme_text(scheme: Scheme) -> str:
    documents = scheme.required_documents or []
    if isinstance(documents, str):
        documents = [documents]
    return "\n".join(filter(None, [
        f"Scheme: {scheme.name}", f"Ministry: {scheme.ministry or scheme.department}",
        f"Objective: {scheme.objective or scheme.description}", f"Eligibility: {scheme.eligibility}",
        f"Benefits: {scheme.benefits}", "Required documents: " + ", ".join(documents),
        f"Application process: {scheme.application_process}", f"Jurisdiction: {scheme.government_level}",
        f"Category: {scheme.category}", f"Exclusions: {scheme.exclusions}",
    ]))


def chunk_text(text: str, size: int = 900, overlap: int = 120) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    chunks, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            boundary = text.rfind(" ", start, end)
            if boundary > start + size // 2:
                end = boundary
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def _embedding(client, text: str, model: str):
    return _embeddings(client, [text], model)[0]


def _embeddings(client, texts: list[str], model: str):
    if not texts:
        return []
    response = client.embeddings.create(model=model, input=texts)
    ordered = sorted(response.data, key=lambda item: item.index)
    return [item.embedding for item in ordered]


def index_scheme(scheme: Scheme, *, client=None, embedding_model="text-embedding-3-small"):
    """Create or refresh the SQL-backed document and chunk index for a scheme."""
    content = searchable_scheme_text(scheme)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    doc = GovernmentDocument.query.filter_by(scheme_id=scheme.id, content_hash=digest).first()
    if doc:
        doc.source_url = scheme.source_url
        doc.source_type = "STRUCTURED_SCHEME"
        doc.last_updated = scheme.last_updated
        doc.verification_status = "DEMO" if scheme.is_demo else ("VERIFIED" if scheme.source_verified else "UNVERIFIED")
        doc.is_current = True
        if client:
            missing = [chunk for chunk in doc.chunks if not chunk.embedding]
            for chunk, vector in zip(missing, _embeddings(client, [chunk.text for chunk in missing], embedding_model)):
                chunk.embedding = vector
        return doc
    # Keep previous versions for auditability; retrieval ranks current scheme data.
    doc = GovernmentDocument(
        scheme_id=scheme.id, title=scheme.name, source_url=scheme.source_url,
        source_type="STRUCTURED_SCHEME",
        verification_status="DEMO" if scheme.is_demo else ("VERIFIED" if scheme.source_verified else "UNVERIFIED"),
        content_hash=digest, content=content, last_updated=scheme.last_updated, is_current=True,
    )
    GovernmentDocument.query.filter_by(scheme_id=scheme.id, source_type="STRUCTURED_SCHEME", is_current=True).update({"is_current": False}, synchronize_session=False)
    db.session.add(doc)
    db.session.flush()
    texts = chunk_text(content)
    vectors = _embeddings(client, texts, embedding_model) if client else [None] * len(texts)
    for index, (text, vector) in enumerate(zip(texts, vectors)):
        db.session.add(DocumentChunk(document_id=doc.id, chunk_index=index, text=text, embedding=vector))
    return doc


def ingest_document(scheme: Scheme, *, title: str, content: str, source_url=None,
                    source_type="OFFICIAL_DOCUMENT", verified=False, client=None,
                    embedding_model="text-embedding-3-small"):
    """Store extracted PDF/text content with source metadata and chunk embeddings."""
    content = re.sub(r"\s+", " ", content).strip()
    if not content:
        raise ValueError("Document contains no extractable text")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    doc = GovernmentDocument.query.filter_by(scheme_id=scheme.id, content_hash=digest).first()
    if doc:
        doc.is_current = True
        doc.source_url = source_url
        doc.source_type = source_type
        if scheme.is_demo:
            doc.verification_status = "DEMO"
        elif verified:
            doc.verification_status = "VERIFIED"
        doc.last_updated = scheme.last_updated
        if client:
            missing = [chunk for chunk in doc.chunks if not chunk.embedding]
            for chunk, vector in zip(missing, _embeddings(client, [chunk.text for chunk in missing], embedding_model)):
                chunk.embedding = vector
        return doc
    GovernmentDocument.query.filter_by(scheme_id=scheme.id, title=title, source_url=source_url,
        source_type=source_type, is_current=True).update({"is_current": False}, synchronize_session=False)
    doc = GovernmentDocument(scheme_id=scheme.id, title=title, source_url=source_url,
        source_type=source_type, content_hash=digest, content=content,
        verification_status="DEMO" if scheme.is_demo else ("VERIFIED" if verified else ("PENDING" if source_url else "UNVERIFIED")),
        last_updated=scheme.last_updated, is_current=True)
    db.session.add(doc)
    db.session.flush()
    if source_url and not scheme.is_demo:
        source = SchemeSource.query.filter_by(scheme_id=scheme.id, source_url=source_url).first()
        if source is None:
            source = SchemeSource(scheme_id=scheme.id, source_url=source_url,
                source_title=title, publisher=scheme.ministry or scheme.department or "Pending review",
                excerpt=content, jurisdiction=scheme.government_level or "Unspecified",
                source_type=source_type, status="VERIFIED" if verified else "PENDING")
            db.session.add(source)
        else:
            source.status = "VERIFIED" if verified else "PENDING"
        if not verified:
            scheme.source_verified = SchemeSource.query.filter_by(
                scheme_id=scheme.id, status="VERIFIED").first() is not None
    texts = chunk_text(content)
    vectors = _embeddings(client, texts, embedding_model) if client else [None] * len(texts)
    for index, (text, vector) in enumerate(zip(texts, vectors)):
        db.session.add(DocumentChunk(document_id=doc.id, chunk_index=index, text=text, embedding=vector))
    return doc


def _cosine(left, right):
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    denom = math.sqrt(sum(a * a for a in left) * sum(b * b for b in right))
    return dot / denom if denom else 0.0


def retrieve(query: str, *, top_k=5, embedding=None, include_demo=False,
             verified_only=True, category=None, scheme_id=None, source_type=None):
    q = DocumentChunk.query.join(GovernmentDocument).join(Scheme).filter(Scheme.active.is_(True))
    if include_demo and not verified_only:
        q = q.filter(db.or_(GovernmentDocument.verification_status == "VERIFIED",
                            GovernmentDocument.verification_status == "DEMO"))
    else:
        q = q.filter(GovernmentDocument.verification_status == "VERIFIED")
    if not include_demo:
        q = q.filter(Scheme.is_demo.is_(False))
    if verified_only:
        q = q.filter(Scheme.source_verified.is_(True))
    if category:
        q = q.filter(Scheme.category == category)
    if scheme_id is not None:
        q = q.filter(Scheme.id == scheme_id)
    if source_type:
        q = q.filter(GovernmentDocument.source_type == source_type)
    chunks = q.all()
    terms = {w.lower() for w in re.findall(r"[\w]+", query) if len(w) > 2}
    ranked = []
    for chunk in chunks:
        doc, scheme = chunk.document, chunk.document.scheme
        if not doc.is_current:
            continue
        if embedding is not None and chunk.embedding:
            score = _cosine(embedding, chunk.embedding)
        else:
            words = {w.lower() for w in re.findall(r"[\w]+", chunk.text) if len(w) > 2}
            score = len(terms & words) / max(len(terms), 1)
        if score > 0:
            ranked.append((score, chunk, scheme, doc))
    ranked.sort(key=lambda row: (row[0], row[1].id), reverse=True)
    return [{
        "score": score, "text": chunk.text, "scheme_id": scheme.id,
        "scheme_name": scheme.name, "category": scheme.category,
        "source_url": doc.source_url or scheme.source_url,
        "source_type": doc.source_type, "document_id": doc.id,
        "chunk_id": chunk.id, "verification_status": doc.verification_status,
        "last_updated": doc.last_updated.isoformat() if doc.last_updated else None,
    } for score, chunk, scheme, doc in ranked[:top_k]]
