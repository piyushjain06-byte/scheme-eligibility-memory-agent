# What changed

Copy these files over your repo (same paths), then run `python upgrade_db.py` once (adds new columns, keeps data).
`rule_engine.py`, `init_db.py`, `ingest_*.py`, `train_chat_model.py`, `test_rule_engine.py`, `test_memory.py`,
`test_user_memory.py`, `test_ingestion_rag.py` and `data/demo_schemes.json` are unchanged.

New files: `agent/normalize.py`, `agent/extraction.py`, `agent/eligibility.py`, `agent/ratelimit.py`,
`routes/account.py`, `reevaluate_all.py`, `tests/test_improvements.py`.
Changed: `app.py`, `config.py`, `.env.example`, `upgrade_db.py`, `database/models.py`, `agent/{memory,user_memory,chat,rag,ingestion,change_detection}.py`,
`routes/api.py`, `templates/index.html`, `tests/test_chat_api.py`.

## Correctness
- **Jurisdiction**: a STATE scheme is only ELIGIBLE for residents of its state (even if the rule never mentions `state`).
  Unknown state -> NEEDS_INFORMATION; other state -> NOT_ELIGIBLE. STATE schemes must now carry `jurisdiction`
  (a state/UT name) when imported.
- **Normalisation**: "obc category", "Jobless", "Woman", "maharashtra" etc. are canonicalised on save, on extraction
  and when comparing with rules.
- **Manual checks**: `manual_checks` (list of strings) on a scheme lists criteria the 14 profile fields cannot express.
  Schemes with no machine-readable rule are reported as `CANNOT_CHECK` instead of being skipped.
- **Wording**: ELIGIBLE is shown as "Likely eligible" with a "confirm on the official portal" note.
- **Rule review**: the admin review queue now returns `proposed_rule_text` (plain English) next to the excerpt.
- **Privacy fix**: the model prompt used to include the citizen's matched values (e.g. "age ... actual: 20").
  It now receives only which criteria were met/failed, never the values.

## Memory
- One source of truth: `CitizenProfile` holds values; `UserMemory` rows hold source / confirmed / previous value / last checked
  and are kept in sync, so profile-form facts and chat facts appear in the same list.
- `date_of_birth` supported; age is derived from it (never stale). Facts like income/age without a DOB are flagged
  "may be out of date" after a while.
- Chat shows "Remembered: age 21 (was 20) [✓] [✕]" so the citizen confirms or forgets what was picked up.
- Much better extraction (natural phrasing, lakh/monthly income, cities, DOB, gender, category, disability, family size) with
  guards against hypotheticals ("if I am 25"), other people ("my father is a farmer") and units ("5 feet tall").
  Optional LLM extractor: `LLM_MEMORY_EXTRACTION=true` (validated and grounded in the user's own words; off by default).
- Follow-ups ("what documents do I need?") keep the previous topic via `Conversation.focus_scheme_ids`.
- Every answer is personalised locally: matched schemes are evaluated and the ones you appear to qualify for come first.

## Operations / privacy
- Retrieval has minimum relevance scores and stop-word filtering; chunks load eagerly.
- Evaluations are only stored when something changed; scheduled `reevaluate_all.py` skips identical repeats.
- Approving a source with a new rule automatically re-evaluates everyone and creates "newly eligible" notifications
  (shown in the UI under Notifications). Run `python reevaluate_all.py` from cron for periodic checks.
- Rate limits (login 10/min, register 5/min, chat 20/min per user; set to 0 to disable) - in-memory, per process.
- Registration needs explicit consent (`REQUIRE_CONSENT`); `GET /api/account/export` downloads all data;
  `DELETE /api/account` (password required) erases it. Demo admin password can come from `DEMO_ADMIN_PASSWORD`.

## Not done (needs you / real data)
- A real, reviewed scheme dataset and rule transcription (the biggest source of wrong answers is still human transcription).
- Encryption of sensitive columns at rest (use disk/DB encryption in deployment); multi-worker rate limiting needs Redis.
- README still describes the older file layout; update it when you next edit it.
