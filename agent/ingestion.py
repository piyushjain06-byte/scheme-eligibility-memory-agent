"""Validated JSON/CSV scheme ingestion into structured and retrieval memory."""
from __future__ import annotations

import csv
import json
import re
from urllib.parse import urlparse
from datetime import date
from pathlib import Path

from database.db import db
from database.models import EligibilityRule, Scheme, SchemeSource
from agent.rag import index_scheme, ingest_document

ALIASES = {
    "scheme name": "name", "scheme_name": "name", "ministry": "ministry",
    "objective": "objective", "eligibility": "eligibility", "benefits": "benefits",
    "required documents": "required_documents", "required_documents": "required_documents",
    "application process": "application_process", "application_process": "application_process",
    "state/central": "government_level", "state_central": "government_level",
    "category": "category", "source url": "source_url", "source_url": "source_url",
    "last updated": "last_updated", "last_updated": "last_updated",
    "source verified": "source_verified", "source_verified": "source_verified",
    "source type": "source_type", "source_type": "source_type",
    "scheme status": "scheme_status", "scheme_status": "scheme_status",
    "exclusions": "exclusions", "description": "description", "department": "department",
    "government_level": "government_level", "application_url": "application_url",
    "active": "active", "rule": "rule", "is_demo": "is_demo",
}
REQUIRED = ("name", "ministry", "objective", "eligibility", "benefits", "required_documents",
            "application_process", "government_level", "category", "source_url", "last_updated",
            "source_verified", "source_type", "scheme_status", "exclusions")


class DatasetValidationError(ValueError):
    pass


def _bool(value, field):
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return False
    if str(value).strip().lower() in {"true", "yes", "1", "verified"}:
        return True
    if str(value).strip().lower() in {"false", "no", "0", "unverified"}:
        return False
    raise DatasetValidationError(f"{field} must be true or false")


def normalize_record(raw, row_number=1):
    if not isinstance(raw, dict):
        raise DatasetValidationError(f"Row {row_number} must be an object")
    row = {}
    for key, value in raw.items():
        canonical = ALIASES.get(str(key).strip().lower(), str(key).strip().lower().replace(" ", "_"))
        row[canonical] = value
    missing = [field for field in REQUIRED if field not in row]
    if missing:
        raise DatasetValidationError(f"Row {row_number}: missing required fields: {', '.join(missing)}")
    if not str(row.get("name") or "").strip():
        raise DatasetValidationError(f"Row {row_number}: scheme name is required")
    row["name"] = str(row["name"]).strip()
    # Legacy demo rows remain importable; absent structured fields become explicit empty values.
    for field in REQUIRED:
        row.setdefault(field, None)
    for field in ("ministry", "objective", "eligibility", "benefits", "application_process", "category",
                  "source_url", "source_type", "scheme_status", "exclusions", "description", "department"):
        if row.get(field) is not None:
            row[field] = str(row[field]).strip()
    docs = row.get("required_documents")
    if isinstance(docs, str):
        try:
            parsed = json.loads(docs)
            docs = parsed if isinstance(parsed, list) else [docs]
        except (ValueError, TypeError):
            docs = [part.strip() for part in docs.split(";") if part.strip()]
    if docs is None:
        docs = []
    if not isinstance(docs, list):
        raise DatasetValidationError(f"Row {row_number}: required_documents must be a list")
    row["required_documents"] = [str(value).strip() for value in docs if str(value).strip()]
    if row.get("last_updated"):
        try:
            row["last_updated"] = date.fromisoformat(str(row["last_updated"])[:10])
        except ValueError as exc:
            raise DatasetValidationError(f"Row {row_number}: last_updated must be YYYY-MM-DD") from exc
    row["source_verified"] = _bool(row.get("source_verified"), "source_verified")
    if row.get("active") not in (None, ""):
        row["active"] = _bool(row["active"], "active")
    else:
        row["active"] = True
    row["is_demo"] = _bool(row.get("is_demo"), "is_demo") or str(row.get("government_level") or "").upper() == "DEMO" or "demo" in str(row.get("description") or "").lower()
    if row["is_demo"]:
        row["source_verified"] = False
        row["government_level"] = "DEMO"
    if row["source_verified"] and not row["is_demo"]:
        parsed = urlparse(str(row.get("source_url") or ""))
        if parsed.scheme != "https" or not parsed.netloc:
            raise DatasetValidationError(f"Row {row_number}: verified schemes require an HTTPS source_url")
    level = str(row.get("government_level") or "").strip()
    if level.casefold() in {"central", "centre", "national"}:
        row["government_level"] = "CENTRAL"
    elif level.casefold() == "state":
        row["government_level"] = "STATE"
    elif level.casefold() == "demo":
        row["government_level"] = "DEMO"
    if row.get("scheme_status"):
        row["scheme_status"] = str(row["scheme_status"]).strip().upper()
    if row.get("rule") == "":
        row["rule"] = None
    if row.get("rule") is not None and not isinstance(row["rule"], dict):
        try:
            row["rule"] = json.loads(row["rule"])
        except (ValueError, TypeError) as exc:
            raise DatasetValidationError(f"Row {row_number}: rule must be JSON") from exc
    if row.get("rule") is not None:
        from agent.rule_engine import evaluate_rule
        known = {field: None for field in ("age", "gender", "state", "district", "annual_income", "occupation", "education_level", "family_size", "marital_status", "disability_status", "student_status", "employment_status", "category", "farmer_status")}
        evaluate_rule(row["rule"], known)
        def fields(node):
            if "field" in node:
                return {node["field"]}
            return set().union(*(fields(child) for child in node.get("conditions", [])))
        unknown = fields(row["rule"]) - set(known)
        if unknown:
            raise DatasetValidationError(f"Row {row_number}: unknown eligibility rule fields: {', '.join(sorted(unknown))}")
    return row


def load_dataset(path):
    path = Path(path)
    if path.suffix.lower() == ".json":
        with path.open(encoding="utf-8") as stream:
            records = json.load(stream)
        if isinstance(records, dict):
            records = records.get("schemes")
    elif path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            records = list(csv.DictReader(stream))
    else:
        raise DatasetValidationError("Input must be a .json or .csv file")
    if not isinstance(records, list) or not records:
        raise DatasetValidationError("Dataset must contain a non-empty list of schemes")
    normalized = [normalize_record(record, index) for index, record in enumerate(records, 1)]
    return _reject_duplicates(normalized)


def _reject_duplicates(rows):
    seen = set()
    for row in rows:
        key = (re.sub(r"\W+", " ", row["name"].casefold()).strip(), (row.get("ministry") or row.get("department") or "").casefold())
        if key in seen:
            raise DatasetValidationError(f"Duplicate scheme in dataset: {row['name']}")
        seen.add(key)
    return rows


def import_records(records, *, embedding_client=None, embedding_model="text-embedding-3-small"):
    normalized = _reject_duplicates([normalize_record(row, index) for index, row in enumerate(records, 1)])
    changed = created = skipped = 0
    for row in normalized:
        is_demo = row["is_demo"]
        ministry = row.get("ministry") or row.get("department")
        scheme = Scheme.query.filter_by(name=row["name"], ministry=ministry).first()
        if scheme is None:
            scheme = Scheme.query.filter_by(name=row["name"]).first()
        if scheme is None:
            scheme = Scheme(name=row["name"], ministry=ministry)
            db.session.add(scheme)
            db.session.flush()
            created += 1
        else:
            changed += 1
        scheme.ministry = ministry
        scheme.department = row.get("department") or ministry
        scheme.description = row.get("objective") or row.get("description")
        scheme.objective = row.get("objective") or row.get("description")
        scheme.eligibility = row.get("eligibility")
        scheme.benefits = row.get("benefits")
        scheme.required_documents = row["required_documents"]
        scheme.application_process = row.get("application_process")
        scheme.government_level = "DEMO" if is_demo else row.get("government_level")
        scheme.category = row.get("category")
        scheme.source_url = row.get("source_url") or row.get("application_url")
        scheme.application_url = row.get("application_url") or row.get("source_url")
        scheme.last_updated = row.get("last_updated")
        scheme.source_verified = bool(row.get("source_verified")) and not is_demo
        scheme.source_type = row.get("source_type")
        scheme.scheme_status = row.get("scheme_status") or "ACTIVE"
        scheme.exclusions = row.get("exclusions")
        scheme.is_demo = is_demo
        scheme.active = row["active"] and str(scheme.scheme_status).upper() not in {"INACTIVE", "CLOSED", "EXPIRED"}
        source = None
        parsed_source = urlparse(str(scheme.source_url or ""))
        if scheme.source_url and parsed_source.scheme == "https" and parsed_source.netloc and not is_demo:
            source = SchemeSource.query.filter_by(scheme_id=scheme.id, source_url=scheme.source_url).first()
            excerpt = "\n".join(filter(None, [scheme.objective, scheme.eligibility, scheme.benefits,
                "Required documents: " + ", ".join(scheme.required_documents or []), scheme.application_process,
                "Exclusions: " + scheme.exclusions if scheme.exclusions else None]))
            if source is None:
                source = SchemeSource(scheme_id=scheme.id, source_url=scheme.source_url,
                    source_title=scheme.name, publisher=ministry or "Government source",
                    excerpt=excerpt or scheme.name,
                    jurisdiction=scheme.government_level or "India",
                    source_type=scheme.source_type or "OFFICIAL_PAGE")
                db.session.add(source)
            source.excerpt = excerpt or scheme.name
            source.status = "VERIFIED" if scheme.source_verified else "PENDING"
            source.proposed_rule_json = row.get("rule") if not scheme.source_verified else None
            if not scheme.source_verified:
                source.rule_version = 0
            source.last_verified = scheme.last_verified if scheme.source_verified else None
        if row.get("rule") and (scheme.source_verified or is_demo):
            latest = scheme.latest_rule()
            if latest is None or latest.rule_json != row["rule"]:
                version = latest.version + 1 if latest else 1
                db.session.add(EligibilityRule(scheme_id=scheme.id, rule_json=row["rule"], version=version))
                scheme.rule_version = version
        if source and scheme.source_verified:
            source.rule_version = scheme.rule_version
        index_scheme(scheme, client=embedding_client, embedding_model=embedding_model)
        if source:
            ingest_document(scheme, title=source.source_title, content=source.excerpt,
                source_url=source.source_url, source_type=source.source_type,
                verified=scheme.source_verified,
                client=embedding_client, embedding_model=embedding_model)
    db.session.commit()
    return {"created": created, "updated": changed, "skipped": skipped, "total": len(normalized)}


def ingest_file(path, *, embedding_client=None, embedding_model="text-embedding-3-small"):
    return import_records(load_dataset(path), embedding_client=embedding_client, embedding_model=embedding_model)
