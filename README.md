# Voice AI Patient Registration Agent

A phone-based intake agent that conversationally registers new patients and persists them to a
database via a REST API.

## Architecture

```
Caller ↔ Vapi (telephony + STT/TTS + LLM orchestration)
              │  tool calls (HTTPS)
              ▼
        FastAPI REST API  ──►  SQLite (SQLAlchemy)
```

- **Telephony + voice + LLM orchestration: Vapi.** Vapi provisions the phone number and handles
  STT (Deepgram), TTS (ElevenLabs), turn-taking, and interruption handling, and drives an LLM
  (GPT-4o) against a system prompt with three tool/function definitions. This lets all the effort
  go into conversation design and the API rather than reimplementing STT/TTS.
- **Backend: FastAPI.** Chosen for fast iteration, built-in request validation via Pydantic, and
  automatic OpenAPI docs — useful both for testing and as a natural fit for Vapi's tool-calling
  (each tool is just an HTTP call to one of these endpoints).
- **Database: SQLite via SQLAlchemy.** Zero setup, file-based persistence, good enough for the
  scope of this assessment. The engine is swappable — set `DATABASE_URL` to a Postgres URL and it
  works unchanged (see `app/database.py`). On a platform with an ephemeral filesystem (e.g. plain
  Vercel serverless), the SQLite file will NOT persist — deploy to a host with a persistent disk
  (Railway, Fly.io with a volume, Render with a persistent disk, or a VM), or point
  `DATABASE_URL` at a hosted Postgres instance (e.g. Railway/Supabase Postgres).
- **Voice agent ↔ database integration**: Vapi's tool calls hit the REST API directly over HTTPS
  (`lookup_patient_by_phone`, `create_patient`, `update_patient`). There's no separate service
  layer — the API *is* the integration point, which keeps validation in one place and makes the
  API independently testable (and independently useful — e.g. a front-desk dashboard could use
  the same API).

## Repo layout

```
app/
  main.py       FastAPI app, all REST endpoints
  models.py     SQLAlchemy Patient model (UUID pk, soft delete via deleted_at)
  schemas.py    Pydantic request/response schemas + all field validation
  database.py   Engine/session setup (SQLite by default, swap via DATABASE_URL)
vapi/
  system_prompt.md       Full conversational system prompt for the voice agent
  assistant_config.json  Vapi assistant definition: model, voice, transcriber, tool schemas
seed.py         Optional: inserts 2 demo patients
requirements.txt
```

## Setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python seed.py          # optional: adds 2 demo patients
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

API is now live at `http://localhost:8000`. Interactive docs at `/docs`.

For a public HTTPS URL Vapi can reach (local dev):
```bash
ngrok http 8000
```

### Environment variables

| Variable       | Required | Default                 | Notes                                      |
|----------------|----------|--------------------------|---------------------------------------------|
| `DATABASE_URL` | No       | `sqlite:///./patients.db`| Set to a Postgres URL for production use.  |

No API keys live in this repo. Vapi and the LLM provider keys are configured in the Vapi
dashboard, not in this codebase — the API itself has no third-party credentials to leak.

### Deployment (Railway example)

1. Push this repo to GitHub.
2. Create a new Railway project from the repo, add a persistent volume mounted where
   `patients.db` will live (or attach Railway Postgres and set `DATABASE_URL`).
3. Set the start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
4. Note the deployed URL, e.g. `https://your-app.up.railway.app`.

### Wiring up Vapi

1. Create a Vapi account, provision a phone number.
2. Create a new assistant. Paste the contents of `vapi/system_prompt.md` as the system prompt.
3. In `vapi/assistant_config.json`, replace every `YOUR_DEPLOYED_API_URL` with your deployed API
   base URL, then create the three tools (`lookup_patient_by_phone`, `create_patient`,
   `update_patient`) in the Vapi dashboard using that JSON as reference (model, voice, and
   transcriber settings included).
4. Attach the assistant to the phone number. Call it.

## API reference

All responses use the envelope `{ "data": ..., "error": ... }`.

| Method | Endpoint                              | Description                                    |
|--------|----------------------------------------|-------------------------------------------------|
| GET    | `/patients`                            | List patients. Filters: `last_name`, `date_of_birth`, `phone_number` |
| GET    | `/patients/{id}`                       | Get one patient by UUID                        |
| POST   | `/patients`                            | Create a patient (returns 201 + record)         |
| PUT    | `/patients/{id}`                       | Partial update                                  |
| DELETE | `/patients/{id}`                       | Soft delete (sets `deleted_at`)                 |
| GET    | `/patients/lookup/by-phone/{phone}`    | Convenience lookup used by the voice agent for duplicate detection |

Validation (server-side, independent of the voice agent): name format, DOB not in the future,
sex enum, 10-digit US phone normalization, 2-letter state, 5-digit/ZIP+4 zip, email format.
Invalid input returns `422` with per-field error details; missing resources return `404`.

## Conversational design notes

The full system prompt is in `vapi/system_prompt.md`, annotated by section. Key decisions:

- **Duplicate detection first.** The agent calls `lookup_patient_by_phone` as soon as it has a
  phone number, before collecting anything else, so it can offer to update an existing record
  instead of creating a duplicate.
- **Confirm-before-save is enforced narratively**, not just structurally — the prompt explicitly
  forbids calling the save tool before an explicit verbal confirmation, and asks for a natural
  spoken summary rather than a field-by-field readout.
- **Corrections and out-of-order info** are handled by instructing the agent to track collected
  fields internally and never re-ask for something already given, and to silently update a field
  on correction rather than restarting.
- **Invalid data** is re-prompted per-field, in plain language ("that date doesn't look right")
  rather than exposing API error codes.
- **Optional fields are offered once, as a batch**, per the spec's conversational note, instead
  of being asked one-by-one for every call.

## Known limitations / trade-offs

- **SQLite, not Postgres.** Fine for this scope and for a single-instance deployment; would move
  to Postgres for concurrent writes at scale (the code already supports this via `DATABASE_URL`).
- **No auth on the API.** Out of scope per the assessment; a production version would put this
  behind at minimum an API key or mTLS between Vapi's webhook caller and this service.
- **State validation is abbreviation-only** (`CA`, not "California") — the LLM is responsible for
  converting spoken state names to abbreviations before calling the tool; this is a reasonable
  place for the LLM to add value rather than duplicating a 50-state name-mapping in the API.
- **No call transcript storage.** Logging currently captures the final collected payload on
  create/update (see `app/main.py` logger calls), not the full conversation transcript. Vapi does
  retain call transcripts/recordings itself, which could be persisted via a webhook to a
  `call_transcripts` table as a next step.
- **Dropped-call recovery is not implemented.** If the call disconnects mid-collection, no partial
  record is saved (nothing is written until the agent successfully calls `create_patient` after
  confirmation) — the caller has to call back and start over. A `pending_registration` staging
  table keyed by phone number, written incrementally, would let the agent resume where it left
  off on the next call.

## Next steps (if given more time)

- Add API key auth on the REST endpoints.
- Persist call transcripts via Vapi's end-of-call webhook.
- Partial-registration recovery on dropped calls.
- Automated tests for the API layer (pytest + `TestClient`, `httpx`).
- A minimal read-only dashboard (`GET /patients` rendered as an HTML table) for the bonus point.
- Multi-language support by switching the Vapi transcriber/voice language when the caller says
  "Hablo español" and mid-call switching the system prompt language instruction.
