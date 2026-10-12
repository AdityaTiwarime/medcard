import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

# fresh throwaway database for every test run, no AI key -> offline mode
_tmp = tempfile.mkdtemp()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.seed import DEMO_PASSWORD  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # runs startup -> tables + seed
        yield c


def login(client, role, ident, pw=DEMO_PASSWORD):
    r = client.post("/api/auth/login", json={"role": role, "identifier": ident, "password": pw, "otp": "123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_frontend_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "MedCard" in r.text


def test_wrong_password_and_wrong_portal_rejected(client):
    assert client.post("/api/auth/login", json={"role": "patient", "identifier": "2507070000057",
                                                "password": "nope", "otp": "123456"}).status_code == 401
    # a patient ID can't open the doctor portal
    assert client.post("/api/auth/login", json={"role": "doctor", "identifier": "2507070000057",
                                                "password": DEMO_PASSWORD, "otp": "123456"}).status_code == 401


def test_api_needs_login(client):
    assert client.get("/api/bootstrap").status_code == 401


def test_patient_sees_only_own_record(client):
    h = login(client, "patient", "2507070000057")
    data = client.get("/api/bootstrap", headers=h).json()
    assert data["role"] == "patient"
    assert [p["id"] for p in data["patients"]] == ["2507070000057"]
    assert data["user"]["reports"] and data["user"]["vitals"]


def test_register_then_login_by_email(client):
    r = client.post("/api/auth/register", json={
        "first_name": "Test", "last_name": "User", "dob": "2000-05-01", "blood": "B+",
        "phone": "+91 90000 00000", "email": "test.user@example.com", "password": "secret123"})
    assert r.status_code == 201, r.text
    assert r.json()["patient_id"].startswith("250707")
    login(client, "patient", "TEST.USER@example.com", "secret123")  # email login is case-insensitive
    dup = client.post("/api/auth/register", json={
        "first_name": "X", "last_name": "Y", "dob": "2000-01-01", "email": "test.user@example.com",
        "password": "secret123"})
    assert dup.status_code == 409


def test_upload_pdf_extracts_text_and_patient_can_download(client):
    import io
    from pypdf import PdfWriter
    # text file proves extraction end to end; a (blank) real PDF proves PDFs are accepted
    h = login(client, "patient", "2507070000057")
    r = client.post("/api/reports/upload", headers=h, data={"name": "Lipid Profile", "type": "Lab"},
                    files={"file": ("lipid.txt", b"Total cholesterol 212 mg/dL, LDL 140 mg/dL, HDL 42 mg/dL",
                                    "text/plain")})
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["has_file"] and "212 mg/dL" in rep["notes"]
    f = client.get(f"/api/reports/{rep['id']}/file", headers=h)
    assert f.status_code == 200 and b"LDL 140" in f.content

    buf = io.BytesIO()
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.write(buf)
    r2 = client.post("/api/reports/upload", headers=h,
                     files={"file": ("scan.pdf", buf.getvalue(), "application/pdf")})
    assert r2.status_code == 201

    bad = client.post("/api/reports/upload", headers=h, files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert bad.status_code == 415


def test_other_patient_cannot_read_my_file(client):
    h_riya = login(client, "patient", "2507070000057")
    rid = client.get("/api/bootstrap", headers=h_riya).json()["user"]["reports"][0]["id"]
    h_diya = login(client, "patient", "2507070000080")
    assert client.get(f"/api/reports/{rid}/file", headers=h_diya).status_code == 404
    assert client.post(f"/api/reports/{rid}/analyze", headers=h_diya).status_code == 404


def test_ai_offline_returns_503_so_ui_can_fall_back(client):
    h = login(client, "patient", "2507070000057")
    assert client.post("/api/ai/complete", headers=h, json={"prompt": "hi"}).status_code == 503


def test_booking_flow_reaches_the_doctor(client):
    h = login(client, "patient", "2507070000080")
    day = (date.today() + timedelta(days=3)).isoformat()
    r = client.post("/api/appointments", headers=h, json={"doctor_id": "DR002", "date": day, "reason": "Cough"})
    assert r.status_code == 201, r.text
    appt = r.json()
    assert appt["doctor"] == "Dr. Amit Shah" and appt["status"] == "Upcoming"
    # same doctor, same day again -> refused
    assert client.post("/api/appointments", headers=h, json={"doctor_id": "DR002", "date": day}).status_code == 409
    # past dates refused
    past = (date.today() - timedelta(days=1)).isoformat()
    assert client.post("/api/appointments", headers=h, json={"doctor_id": "DR002", "date": past}).status_code == 422

    hd = login(client, "doctor", "DR002")
    mine = client.get("/api/bootstrap", headers=hd).json()["user"]["appointments"]
    assert any(a["id"] == appt["id"] for a in mine)
    done = client.patch(f"/api/appointments/{appt['id']}", headers=hd, json={"status": "Completed"})
    assert done.status_code == 200 and done.json()["status"] == "Completed"
    # a different doctor can't touch it
    ho = login(client, "doctor", "DR001")
    assert client.patch(f"/api/appointments/{appt['id']}", headers=ho, json={"status": "Cancelled"}).status_code == 403


def test_doctor_adds_report_patient_sees_it(client):
    hd = login(client, "doctor", "priya.mehta@medcard.ai")
    r = client.post("/api/reports", headers=hd, json={"patient_id": "2507070000057", "name": "2D Echo",
                                                      "type": "Cardiac", "status": "Normal", "notes": "EF 60%"})
    assert r.status_code == 201
    hp = login(client, "patient", "2507070000057")
    names = [x["name"] for x in client.get("/api/bootstrap", headers=hp).json()["user"]["reports"]]
    assert "2D Echo" in names
    # patients can't add reports through the doctor endpoint
    assert client.post("/api/reports", headers=hp, json={"patient_id": "2507070000057", "name": "x"}).status_code == 403


def test_vitals_logging_and_validation(client):
    h = login(client, "patient", "2507070000057")
    r = client.post("/api/vitals", headers=h, json={"systolic": 120, "diastolic": 80, "heart_rate": 70})
    assert r.status_code == 201
    latest = client.get("/api/bootstrap", headers=h).json()["user"]["vitals"][0]
    assert latest["systolic"] == 120
    assert client.post("/api/vitals", headers=h, json={}).status_code == 422
    assert client.post("/api/vitals", headers=h, json={"heart_rate": 900}).status_code == 422


def test_admin_policies(client):
    ha = login(client, "admin", "admin@medcard.ai")
    assert client.post("/api/policies", headers=ha, json={"title": "Data Retention Policy"}).status_code == 201
    hp = login(client, "patient", "2507070000057")
    assert client.post("/api/policies", headers=hp, json={"title": "Hack"}).status_code == 403
    titles = [p["title"] for p in client.get("/api/bootstrap", headers=ha).json()["policies"]]
    assert "Data Retention Policy" in titles


def test_public_card_is_anonymized_and_token_can_be_reset(client):
    h = login(client, "patient", "2507070000057")
    token = client.get("/api/bootstrap", headers=h).json()["user"]["card_token"]
    card = client.get(f"/api/public/card/{token}").json()
    assert card["blood"] == "O+" and card["reports"]
    flat = str(card)
    assert "Riya" not in flat and "2507070000057" not in flat and "98765 00057" not in flat
    new = client.post("/api/card/regenerate", headers=h).json()["card_token"]
    assert client.get(f"/api/public/card/{token}").status_code == 404
    assert client.get(f"/api/public/card/{new}").status_code == 200


def test_qr_png(client):
    r = client.get("/api/qr.png", params={"data": "https://example.com/#card=abc"})
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_user_text_is_html_escaped(client):
    h = login(client, "patient", "2507070000080")
    r = client.post("/api/reports/upload", headers=h, data={"name": "<img src=x onerror=alert(1)>"},
                    files={"file": ("a.txt", b"<script>alert(1)</script>", "text/plain")})
    assert r.status_code == 201
    body = r.json()
    assert "<img" not in body["name"] and "&lt;img" in body["name"]
    assert "<script>" not in body["notes"]


def test_ai_analysis_is_saved_and_escaped(client, monkeypatch):
    from app import ai
    seen = {}

    def fake_complete(user_id, prompt, system=None, history=None, max_tokens=1000, image=None, api_key=None):
        seen["prompt"] = prompt
        return "📋 SUMMARY\nLDL is high. <script>alert(1)</script>"

    monkeypatch.setattr(ai, "complete", fake_complete)
    h = login(client, "patient", "2507070000057")
    up = client.post("/api/reports/upload", headers=h, data={"name": "Lipids"},
                     files={"file": ("l.txt", b"LDL 165 mg/dL", "text/plain")}).json()
    r = client.post(f"/api/reports/{up['id']}/analyze", headers=h)
    assert r.status_code == 200
    assert "LDL 165 mg/dL" in seen["prompt"]            # the AI saw the real file text
    assert "<script>" not in r.json()["analysis"]        # escaped before it reaches the browser
    saved = [x for x in client.get("/api/bootstrap", headers=h).json()["user"]["reports"] if x["id"] == up["id"]][0]
    assert "LDL is high" in saved["ai_summary"] and saved["status"] == "Review"


def test_login_needs_otp_and_checks_name(client):
    base = {"role": "patient", "identifier": "2507070000057", "password": DEMO_PASSWORD}
    assert client.post("/api/auth/login", json=base).status_code == 401                      # no OTP
    assert client.post("/api/auth/login", json={**base, "otp": "000000"}).status_code == 401  # wrong OTP
    assert client.post("/api/auth/login", json={**base, "otp": "123456", "name": "Diya Jain"}).status_code == 401
    assert client.post("/api/auth/login", json={**base, "otp": "123456", "name": "riya jain"}).status_code == 200


def test_users_own_api_key_is_passed_to_ai(client, monkeypatch):
    from app import ai
    seen = {}

    def fake_complete(user_id, prompt, system=None, history=None, max_tokens=1000, image=None, api_key=None):
        seen["key"] = api_key
        return "ok"

    monkeypatch.setattr(ai, "complete", fake_complete)
    h = login(client, "patient", "2507070000057")
    r = client.post("/api/ai/complete", headers={**h, "X-AI-Key": "sk-ant-test"}, json={"prompt": "hi"})
    assert r.status_code == 200 and seen["key"] == "sk-ant-test"
    assert ai.key_provider("sk-ant-x") == "anthropic" and ai.key_provider("sk-proj-x") == "openai"


def test_qr_card_has_full_report_details(client):
    h = login(client, "patient", "2507070000057")
    token = client.get("/api/bootstrap", headers=h).json()["user"]["card_token"]
    cbc = [r for r in client.get(f"/api/public/card/{token}").json()["reports"] if r["name"] == "Blood Count Report"][0]
    assert ["Hemoglobin", "13.2 g/dL ✓", "ok"] in cbc["values"] and cbc["conclusion"].startswith("Conclusion:")
    # uploaded reports get their values read from the text automatically
    client.post("/api/reports/upload", headers=h, data={"name": "Vit D"},
                files={"file": ("v.txt", b"Vitamin D 14 ng/mL (low), Calcium 9.1 mg/dL", "text/plain")})
    vit = [r for r in client.get(f"/api/public/card/{token}").json()["reports"] if r["name"] == "Vit D"][0]
    assert ["Vitamin D", "14 ng/mL ⚠", "warn"] in vit["values"] and ["Calcium", "9.1 mg/dL ✓", "ok"] in vit["values"]
