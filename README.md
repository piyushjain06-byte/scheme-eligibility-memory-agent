# Scheme Eligibility Memory Agent

**An AI agent that remembers who you are — so government schemes don't have to ask twice.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)]()
[![Flask](https://img.shields.io/badge/Flask-3.x-black)]()
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-ORM-red)]()
[![Bootstrap](https://img.shields.io/badge/Bootstrap-5-purple)]()
[![License](https://img.shields.io/badge/License-MIT-green)]()

---

## Table of Contents

1. [Overview](#overview)
2. [The Problem](#the-problem)
3. [Core AI Concept](#core-ai-concept)
4. [Features](#features)
5. [System Architecture](#system-architecture)
6. [Tech Stack](#tech-stack)
7. [Project Structure](#project-structure)
8. [Database Schema](#database-schema)
9. [How the Rule Engine Works](#how-the-rule-engine-works)
10. [Why This Is a "Memory Agent"](#why-this-is-a-memory-agent)
11. [Installation & Setup](#installation--setup)
12. [Demo Credentials](#demo-credentials)
13. [Demo Workflow](#demo-workflow)
14. [Testing](#testing)
15. [Team](#team)
16. [Disclaimer](#disclaimer)

---

## Overview

**Scheme Eligibility Memory Agent** is a full-stack AI mini-project built for an AI/Agents coursework submission. It reimagines how citizens discover government welfare schemes.

Instead of forcing a citizen to fill out a fresh eligibility questionnaire for every single scheme, this system asks for their profile **once**, stores it as **persistent memory**, and then continuously reasons over that memory against a growing knowledge base of schemes — automatically surfacing new eligibility, tracking policy changes, and explaining every decision in plain language.

It is built to demonstrate core AI agent concepts — **memory, knowledge representation, deterministic reasoning, and proactive change detection** — without relying on an LLM to make the actual eligibility decision, keeping the system fully explainable, auditable, and reproducible.

## The Problem

Government scheme portals today follow a repetitive, stateless pattern:

```
User → answers 20 questions → checks Scheme A
User → answers the same 20 questions → checks Scheme B
User → answers the same 20 questions again → checks Scheme C
```

Every scheme check starts from zero. Nothing is remembered. Nothing is proactive. If a scheme's income limit changes next month and a citizen suddenly qualifies, no one tells them — they'd have to go back and re-check manually.

This project replaces that pattern with:

```
User → provides profile once → persistent memory
Agent → retrieves memory → checks Scheme A, B, C, D...
Agent → monitors profile & policy changes over time
Agent → proactively notifies the user of new eligibility
```

## Core AI Concept

The system is built around five cooperating components:

| Component | Role |
|---|---|
| **Memory** | Persistently stores the citizen's profile so it's never re-asked |
| **Knowledge Base** | Stores government scheme data and their eligibility rules |
| **Reasoning (Rule Engine)** | Deterministically evaluates profile vs. rules |
| **Agent** | Coordinates memory retrieval, scheme lookup, reasoning, and explanation generation |
| **Change Detection** | Re-evaluates and notifies when a profile or a scheme's rules change |

Deliberately, **the eligibility decision itself is never made by an LLM.** An LLM (if used at all) is restricted to understanding natural-language queries and phrasing friendly explanations — the actual ELIGIBLE / NOT_ELIGIBLE / NEEDS_INFORMATION verdict always comes from the deterministic rule engine acting on stored memory. This keeps every decision explainable and reproducible — a requirement for anything touching real eligibility logic.

## Current implementation

- Persistent citizen profile memory with registration, login, and profile APIs
- Persistent conversation history and explicit scheme-relevant memory facts, with view/update/delete controls
- Deterministic eligibility engine with `==`, `!=`, `<`, `<=`, `>`, `>=`,
  `between`, `in`, and nested `AND` / `OR` / `NOT`
- Minimal browser chat page and JSON chat endpoint
- Admin-only import and review endpoints for scheme metadata and official-source evidence
- Chat answers grounded in reviewed source excerpts, with source URL citations
- JSON/CSV dataset ingestion and a local SQL-backed chunk index with optional semantic embeddings
- Eligibility checks remain local and deterministic; profile fields are not sent
  in the OpenAI prompt
- Optional OpenAI fine-tuning job submission for curated conversational examples

The repository does not include real government scheme records or a completed
fine-tuned model. It does not automatically crawl/recheck official portals,
provide a full admin dashboard, or send notifications. The sample scheme JSON
is fictional demonstration data.

## System Architecture

```
                          CITIZEN
                             │
                             ▼
                   HTML + Bootstrap UI
                             │
                             ▼
                       Flask Backend
                             │
             ┌───────────────┼───────────────┐
             ▼               ▼               ▼
        Memory Store       Agent         Scheme KB
     (CitizenProfile)       │          (Scheme + Rules)
             │               ▼               │
             │          Rule Engine           │
             │               │               │
             └───────────────┼───────────────┘
                             ▼
                    Eligibility Result
                             │
                  ┌──────────┴──────────┐
                  ▼                     ▼
             Explanation           Notification
```

The architecture is intentionally modular — memory operations, rule evaluation, and UI rendering are kept in separate layers so each can be tested, explained, and demoed independently.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, Flask |
| ORM / Database | SQLAlchemy, SQLite |
| Frontend | HTML5, CSS, Bootstrap 5, vanilla JavaScript |
| Data interchange | JSON (rule definitions, scheme knowledge base) |
| Auth | Flask sessions, Werkzeug password hashing |

No Django, no Streamlit, no frontend frameworks (React/Vue/Angular) — by design, to keep the stack lean and every layer explainable in a viva.

## Project Structure

```
scheme-eligibility-agent/
│
├── app.py                     # Flask app factory + blueprint registration
├── config.py                  # App configuration
├── init_db.py                 # DB setup: tables, demo admin, seed schemes
├── requirements.txt
├── README.md
│
├── database/
│   ├── models.py               # User, CitizenProfile, Scheme, EligibilityRule,
│   │                            # EligibilityEvaluation, Notification
│   └── db.py                   # Shared SQLAlchemy instance
│
├── agent/
│   ├── memory.py                # save/get/update profile, missing-attribute detection
│   ├── agent.py                 # Orchestrates memory → KB → rule engine → explanation
│   ├── rule_engine.py           # Deterministic eligibility evaluation
│   └── intent.py                # Natural-language intent detection for chat queries
│
├── services/
│   ├── eligibility_service.py   # Eligibility lookups/formatting for routes
│   ├── evaluation_service.py    # Re-evaluation + eligibility-change detection
│   ├── notification_service.py  # Notification creation, de-duplication
│   └── scheme_service.py        # Scheme CRUD for admin
│
├── routes/
│   ├── auth.py                  # Register / login / logout
│   ├── citizen.py                # Dashboard, profile, history
│   ├── schemes.py                # Scheme browsing & detail
│   ├── agent.py                  # Chat / "Ask the Agent" endpoint
│   └── admin.py                  # Admin dashboard, scheme + rule management
│
├── data/
│   └── demo_schemes.json        # 10 demo schemes with rule definitions
│
├── templates/                   # Jinja2 + Bootstrap templates (citizen + admin/)
├── static/                      # CSS and JS
└── tests/                       # Unit tests: memory, rule engine, eligibility
```

## Database Schema

| Model | Purpose |
|---|---|
| **User** | Login identity — `username`, `email`, `password_hash`, `role` (`citizen`/`admin`) |
| **CitizenProfile** | The persistent memory of a citizen — income, occupation, location, family details, etc. |
| **Scheme** | A government scheme's metadata — name, department, benefits, active status, current rule version |
| **EligibilityRule** | Versioned rule definitions (`rule_json`) per scheme — a new version is created whenever eligibility criteria change |
| **EligibilityEvaluation** | A record of every evaluation ever run — status, reasons, failed conditions, missing fields, and which rule version produced it |
| **Notification** | Alerts sent to a citizen — new eligibility, rule change, profile change, or general |

Every evaluation is tied to the exact rule version that produced it, so eligibility history remains accurate even after a scheme's rules are updated later.

## How the Rule Engine Works

Each scheme's `EligibilityRule.rule_json` encodes a logic tree, e.g.:

```json
{
  "logic": "AND",
  "conditions": [
    { "field": "age", "operator": "between", "value": [18, 25] },
    { "field": "student_status", "operator": "==", "value": true },
    { "field": "annual_income", "operator": "<=", "value": 250000 }
  ]
}
```

The rule engine takes this tree plus the citizen's memory dict (`CitizenProfile.to_memory_dict()`) and returns one of three deterministic outcomes:

```python
# All conditions checkable and satisfied
{"status": "ELIGIBLE", "reasons": [...], "failed_conditions": [], "missing_fields": []}

# All conditions checkable but at least one fails
{"status": "NOT_ELIGIBLE", "reasons": [], "failed_conditions": [...], "missing_fields": []}

# One or more fields needed by the rule aren't in memory yet
{"status": "NEEDS_INFORMATION", "reasons": [], "failed_conditions": [], "missing_fields": [...]}
```

Supported operators: `==`, `!=`, `<`, `<=`, `>`, `>=`, `between`, `in`
Supported logic: `AND`, `OR`, `NOT` (nestable)

This makes every decision fully explainable — the reasons and failed conditions returned are never generated freeform, only derived directly from which specific rule conditions passed or failed.

## Why This Is a Memory Agent

The profile persists across sessions until the user updates or clears it. The
chat can ask only for fields missing from a particular eligibility rule. An
administrator can manually re-run a scheme after a source or rule update; if a
user changes to `ELIGIBLE`, the system creates an in-app notification.
Automatic policy monitoring and outbound notifications are not implemented.

## Installation & Setup

```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/scheme-eligibility-agent.git
cd scheme-eligibility-agent

# 2. Install dependencies
pip install -r requirements.txt

# 3. Initialize the database (creates tables, demo admin, imports 10 demo schemes safely)
python init_db.py

# 4. Copy .env.example to .env and set SECRET_KEY and (optionally) OPENAI_API_KEY.

# 5. Run the app
python app.py
```

The app will be available at `http://127.0.0.1:5000`. For an existing database,
run `python upgrade_db.py` to add tables and columns without dropping records.
`init_db.py` preserves existing data; use `--reset --confirm-reset` only for a
disposable local database.

### Grounded chat API

The API uses the existing deterministic rule engine for eligibility. OpenAI is
used only to phrase answers from reviewed evidence; citizen profile fields are
kept local and are not added to the model prompt. The citizen's chat message is
sent to the configured OpenAI API, so do not include identifiers or secrets in
messages.

Set these environment variables before starting the service:

```text
SECRET_KEY=<a long random secret that remains stable between restarts>
OPENAI_API_KEY=<OpenAI API key>
OPENAI_CHAT_MODEL=<base model or your fine-tuned model ID>
EMBEDDING_MODEL=text-embedding-3-small
OPENAI_FINE_TUNE_BASE_MODEL=<fine-tunable base model ID, only needed for training>
SESSION_COOKIE_SECURE=true
```

Use HTTPS and set `SESSION_COOKIE_SECURE=true` outside local development.
Without `OPENAI_API_KEY`, verified-source LLM chat returns `503`. When the
database has only demo rows, the app can still show deterministic demo results
with an explicit `DEMO / TEST DATA ONLY` warning and no citations or placeholder
links. Demo rows are never treated as verified evidence and are excluded from
public retrieval even if an import marks one verified.

API endpoints:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/register` | Create a citizen account and start a session |
| `POST` | `/api/login` / `/api/logout` | Start or end a session |
| `GET` / `PUT` | `/api/profile` | Read or update the signed-in citizen's memory |
| `GET` / `DELETE` | `/api/memory` | View or clear durable remembered facts |
| `PUT` / `DELETE` | `/api/memory/<key>` | Update or forget one profile fact |
| `GET` / `DELETE` | `/api/conversations` | View or clear chat history |
| `POST` | `/api/chat` | Ask a question; returns answer, citations, deterministic results, and conversation ID |
| `POST` | `/api/admin/schemes/import` | Admin-only structured scheme import |
| `POST` | `/api/admin/documents/import` | Admin-only extracted text import for a scheme |
| `POST` | `/api/admin/index/rebuild` | Rebuild chunks; creates embeddings when configured |
| `GET` | `/api/admin/ingestion/errors` | View failed admin imports |
| `POST` | `/api/admin/schemes/<id>/reevaluate` | Manually re-run one scheme and notify newly eligible users |
| `GET` | `/api/notifications` | View the signed-in citizen's notifications |
| `POST` | `/api/admin/sources/import` | Admin-only import; every source starts `PENDING` |
| `GET` | `/api/admin/sources?status=PENDING` | Admin-only review queue (`PENDING`, `VERIFIED`, or `REJECTED`) |
| `POST` | `/api/admin/sources/<id>/review` | Admin-only approval/rejection; only `VERIFIED` sources can ground chat |

### Dataset and document ingestion

Import team-collected structured data with:

```bash
python ingest_schemes.py data/schemes.json
python ingest_schemes.py data/schemes.csv --no-embeddings
```

The canonical columns are `Scheme Name`, `Ministry`, `Objective`,
`Eligibility`, `Benefits`, `Required Documents`, `Application Process`,
`State/Central`, `Category`, `Source URL`, `Last Updated`, `Source Verified`,
`Source Type`, `Scheme Status`, and `Exclusions`. JSON may be a list or an
object containing `schemes`; CSV uses these names as headers. Imports validate
required columns, dates, booleans, rules and duplicates, then upsert scheme
records, retain source metadata, and create searchable document chunks.
Eligibility rule trees may be supplied in an additional `rule` field.

The local SQL database stores chunk text, metadata and optional embedding
vectors. Semantic ranking uses cosine similarity; without embeddings, retrieval
uses a lexical score. This keeps the SQLite-first project easy to run locally.
The retrieval layer is isolated so a larger deployment can replace it with
FAISS or Chroma.

Add local document knowledge to a scheme with:

```bash
python ingest_documents.py path/to/notification.pdf --scheme-id 1 --source-url https://example.gov.in/notification
```

PDF, TXT and Markdown are supported. Text extraction and indexing do not make
a document verified; public answers still require reviewed source evidence.
The source URL, type, document/chunk IDs, verification state and update date
are kept with indexed chunks.

Explicit statements in chat can populate structured profile memory (such as
age, state, student status, education, employment and income). Messages and
conversations persist. Users can view/edit/delete facts and clear profile
memory independently from conversation history. The current extractor uses
simple explicit phrasing and does not save uncertain inferences. Profile
values are used locally by deterministic eligibility checks and are not sent
to OpenAI; recent conversation text is sent as context for answer phrasing.

Registration and protected endpoints use Flask's signed session cookie. The
demo admin is for local development only; do not deploy its credentials.

Import records as JSON using `/api/admin/sources/import` after logging in as an
administrator. Each record needs scheme metadata plus an HTTPS source URL,
publisher, title, jurisdiction, and a verbatim supporting excerpt. An optional
`rule` uses the deterministic rule-tree format described above. Imports are
pending review; an administrator must compare each excerpt and rule with the
official source and approve it before it can be used. Use one record per
scheme/source pair. Re-importing the same scheme and URL is idempotent.

Example record:

```json
{
  "name": "Example State Scheme",
  "description": "Summary copied from an official notification.",
  "department": "Example Department",
  "government_level": "STATE",
  "category": "Education",
  "benefits": "As stated in the official notification.",
  "source_url": "https://example.gov.in/scheme-notification",
  "source_title": "Scheme notification",
  "publisher": "Example Department",
  "excerpt": "Exact relevant text from the official notification.",
  "jurisdiction": "Example State",
  "rule": {
    "logic": "AND",
    "conditions": [
      { "field": "age", "operator": ">=", "value": 18 }
    ]
  }
}
```

This is an ingestion and review foundation, not a complete or automatically
maintained catalogue of Indian schemes. Coverage across all states and union
territories requires acquiring, importing, reviewing, and periodically
rechecking each official source. Fine-tuning changes response style, not the
source of policy facts; use a fine-tuned model ID only for a model trained on
curated conversational examples. Never put changing scheme rules or citizen
profiles in fine-tuning data.

The `/` page provides a minimal login, profile, and chat interface. To submit
a fine-tuning job, prepare a JSONL file of curated, de-identified
`{"messages":[...]}` examples with assistant answers ending each conversation,
set `OPENAI_FINE_TUNE_BASE_MODEL`, and run:

```bash
python train_chat_model.py path/to/curated-examples.jsonl
```

This uploads the supplied file to OpenAI and starts a paid fine-tuning job.
Only include examples that teach safe conversation style and source citation;
do not include citizen details or policy facts that can change. After training,
set `OPENAI_CHAT_MODEL` to the returned fine-tuned model ID. Training is not
run automatically, and no API key or training corpus is included in this repo.

## Demo Credentials

> ⚠️ **Development/demo credentials only — do not reuse in any real deployment.**

| Role | Username | Password |
|---|---|---|
| Admin | `admin` | `Admin@123` |

Citizen accounts are created via the registration page.

## Demo Workflow

1. Configure `SECRET_KEY` and `OPENAI_API_KEY`, then start the app.
2. Sign in as the development admin and import records copied from official
   sources. Imported records remain pending until reviewed.
3. Review the source and its eligibility rule, then mark the source `VERIFIED`.
4. Register as a citizen, save profile details, and ask the chat page about
   schemes or eligibility.
5. Log out and back in; the saved profile remains available to the rule engine.

This demo flow covers the implemented chat and memory foundation. National
coverage depends on building and maintaining a reviewed data catalogue; no
real all-India corpus is bundled.

## Testing

```bash
python -m pytest tests/
```

Covers profile memory, deterministic rules and missing fields, authentication,
source review, chat citations, import validation, duplicate detection, demo
isolation, retrieval, and conversation/memory controls. Run with
`python -m pytest -q`.

## Team

Built by a team of 4 for an AI coursework mini-project, with work divided across:

1. **Data & Foundation** — database models, app factory, DB seeding
2. **AI Core** — memory system, rule engine, agent orchestration, intent detection
3. **Services & Routes** — business logic, evaluation/notification services, Flask routes, auth
4. **Frontend & UX** — citizen and admin templates, styling, client-side interactivity

## Disclaimer

All scheme names, benefit amounts, and eligibility criteria in `data/demo_schemes.json` are **fictional and clearly labeled as demo data**, created solely for academic demonstration. They do not represent real government schemes. If real scheme data is ever integrated, its criteria must be verified against official government sources before use.

---

*This project was built to demonstrate applied AI agent concepts — memory, knowledge representation, deterministic reasoning, and change detection — as part of an academic AI course submission.*
