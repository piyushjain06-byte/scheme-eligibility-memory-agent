# Scheme Eligibility Memory Agent

**An AI agent that remembers who you are — so government schemes don't have to ask twice.**


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

## Features

- ✅ Persistent citizen profile (long-term memory) — filled once, reused everywhere
- ✅ Government scheme knowledge base with versioned eligibility rules
- ✅ Deterministic rule engine supporting `==`, `!=`, `<`, `<=`, `>`, `>=`, `between`, `in`, with `AND` / `OR` / `NOT` logic
- ✅ Explainable eligibility results — every verdict comes with human-readable reasons
- ✅ Missing-information detection — the agent only asks for what it doesn't already know
- ✅ Full eligibility history per citizen, per scheme, per rule version
- ✅ Newly-eligible detection when a profile or a rule changes
- ✅ Rule versioning — old evaluations remain traceable to the rule version that produced them
- ✅ Notification system (new eligibility, rule changes, profile changes)
- ✅ Admin dashboard for scheme management and manual re-evaluation
- ✅ Natural-language "Ask the Agent" chat interface
- ✅ Role-based authentication (citizen / admin) with hashed passwords and protected routes

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

## Why This Is a "Memory Agent"

The differentiator from a standard scheme-lookup portal is **statefulness**:

- A citizen's profile is saved once and reused for every scheme, every session, forever — never re-asked.
- If a scheme needs one field the citizen hasn't provided yet, the agent asks **only for that field**, not the entire form again.
- The system actively watches for two kinds of change:
  - **Profile change** (e.g. occupation changes from *unemployed* to *student*) → affected schemes are automatically re-evaluated.
  - **Rule change** (e.g. an admin raises a scheme's income limit) → every citizen's evaluation for that scheme is automatically re-run.
- Whenever either kind of change flips a citizen's status from `NOT_ELIGIBLE`/`NEEDS_INFORMATION` to `ELIGIBLE`, a notification is generated — this is the "proactive" part of the agent.

## Installation & Setup

```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/scheme-eligibility-agent.git
cd scheme-eligibility-agent

# 2. Install dependencies
pip install -r requirements.txt

# 3. Initialize the database (creates tables, demo admin, seeds 10 demo schemes)
python init_db.py

# 4. Run the app
python app.py
```

The app will be available at `http://127.0.0.1:5000`.

## Demo Credentials

> ⚠️ **Development/demo credentials only — do not reuse in any real deployment.**

| Role | Username | Password |
|---|---|---|
| Admin | `admin` | `Admin@123` |

Citizen accounts are created via the registration page.

## Demo Workflow

A complete demonstration of the memory-agent behavior, end to end:

1. **Register** as a citizen.
2. **Enter profile details** once — age, state, occupation, annual income, education, family size.
3. **Save** the profile — it's now persisted as memory.
4. **Ask the agent**: *"What schemes am I eligible for?"* — the agent retrieves memory, evaluates it against all active schemes, and returns explained results.
5. **Log out, then log back in.** Ask again — the agent answers immediately from memory without re-asking any profile question.
6. **Admin adds a new scheme.**
7. **Admin runs re-evaluation** from the admin dashboard.
8. **Citizen logs in** and sees a *"You are newly eligible!"* notification for the new scheme.
9. **Admin changes an existing scheme's eligibility rule** (e.g. raises the income limit), creating a new rule version.
10. **Re-evaluation runs automatically**; the citizen's eligibility history now shows the status change alongside the old and new rule versions.

This flow is the core proof-of-concept for the entire project: **memory persists, reasoning is deterministic, and the agent proactively surfaces change** — without ever re-asking a question it already has the answer to.

## Testing

```bash
python -m pytest tests/
```

Covers:
- Memory persistence — save, retrieve, update, missing-attribute detection
- Rule engine — `AND`/`OR`/`NOT` logic, all supported operators, missing-field handling
- Eligibility-change detection — all four status transition combinations (`ELIGIBLE ↔ NOT_ELIGIBLE`, etc.), ensuring only *meaningful* transitions trigger notifications

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
