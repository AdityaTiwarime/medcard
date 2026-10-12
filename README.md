# MedCard AI: Integrated Medical E-Card Platform

A full-stack health records platform with three portals (**Patient**, **Doctor**, **Superadmin**), AI report analysis, and a scannable **emergency QR card** that shows first responders what they need (blood type, allergies, conditions, reports) without revealing who the patient is.

**Live demo:** _add your Render link here_. Demo password for every portal: `Demo@123`, OTP: `123456`

| Portal | Log in with |
|---|---|
| Patient | `2507070000057` (Riya Jain) or `2507070000080` (Diya Jain) |
| Doctor | `DR001`, `DR002` or `DR003` |
| Superadmin | `admin@medcard.ai` |

## What it does

**Patients**
- Register and log in with ID/email + password + OTP, with an optional full-name check (bcrypt-hashed passwords, JWT sessions). The OTP is a demo code (`LOGIN_OTP`, default `123456`) until an SMS provider is connected
- Upload reports (PDF / image / text, up to 5 MB). Text is extracted from PDFs on upload, and the AI reads the real file (including photographed reports)
- AI analysis is saved to the report, so it isn't re-generated (and re-billed) on every view
- Book appointments with a chosen doctor and date; cancel them
- Log vitals; the dashboard flags borderline and abnormal readings using standard clinical ranges
- AI health assistant and risk predictor, grounded in the patient's own records. Users can paste their own API key in the chat (kept in their browser, used per request, never stored on the server)
- Download any report: the original file, or a text summary with its AI analysis
- Medical e-card with a QR code that opens a live, anonymized emergency view (every report has "View Full Report" with test values, ⚠/✗ flags and the doctor's note; values are read automatically from uploaded reports); the link can be reset if a card is lost

**Doctors**
- See every patient's record, ask the AI for a clinical summary
- Full appointment schedule with specialty; mark their own visits completed or cancelled
- File reports directly into a patient's record

**Superadmin**
- All users, platform analytics, publish health policies

## Architecture

```
Browser (single-page app, static/index.html)
   │  fetch + JWT bearer token
   ▼
FastAPI (app/main.py)
   ├── auth: bcrypt passwords, role-checked JWT (patient / doctor / admin)
   ├── records: reports (+ file storage & PDF text extraction), appointments, vitals, policies
   ├── AI proxy (app/ai.py): Claude or OpenAI, key stays on the server, per-user hourly limit
   └── QR: PNG generation + public anonymized card by unguessable token
   ▼
SQLAlchemy → PostgreSQL (production) / SQLite (local)
```

## Security decisions

- **API keys never reach the browser.** The original prototype asked users to paste an Anthropic key into the page; now all AI calls go through the backend, with a per-user hourly limit.
- **Role checks on every endpoint.** Patients can only read their own records and files; only a visit's own doctor can change it; only admins publish policies (covered by tests).
- **Stored-XSS protection.** The UI renders with `innerHTML`, so all user-supplied text is HTML-escaped by the API, and AI replies are escaped in the browser. Without this, a report named `<img onerror=…>` would run inside a doctor's session.
- **Emergency card is anonymized.** No name, patient ID or phone number; the token is random (144-bit) and can be rotated by the patient.

## Run locally

```bash
pip install -r requirements-dev.txt
uvicorn app.main:app --reload          # http://localhost:8000
pytest -q                              # 19 API tests (SQLite, or set DATABASE_URL for Postgres)
```

The database is created and filled with demo data on first start. Copy `.env.example` to `.env` for options (Postgres URL, JWT secret, AI key).

AI is optional: without `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`, the assistant answers from built-in offline responses and report analysis shows a clear "AI offline" notice.

## Tests

- `tests/test_api.py`: 19 tests covering auth (password, OTP, name check), role isolation, uploads, AI analysis (with a simulated model), booking rules (no past dates, no double booking), vitals validation, admin-only actions, card anonymization and token reset, and XSS escaping. They pass on both SQLite and PostgreSQL.
- `tests/e2e_browser.py`: a Playwright click-through of all three portals in a real browser (`python tests/e2e_browser.py http://localhost:8000 ./shots`).

## Deploy

See **DEPLOY.md** (Render + free Neon Postgres, about 20 minutes).

## Tech stack

Python, FastAPI, SQLAlchemy, PostgreSQL, JWT, bcrypt, pypdf, qrcode, Anthropic / OpenAI APIs, HTML/CSS/JavaScript, Docker, Playwright, pytest
