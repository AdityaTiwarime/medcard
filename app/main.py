"""MedCard AI backend: auth, records, appointments, vitals, policies, AI and the emergency QR card."""
import html
import io
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import qrcode
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, EmailStr, Field
from pypdf import PdfReader
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import ai
from .database import Base, SessionLocal, engine, get_db
from .models import Appointment, Doctor, Patient, Policy, Report, User, Vital, new_card_token, utcnow
from .security import current_user, hash_password, make_token, require, verify_password
from .seed import seed

STATIC = Path(__file__).resolve().parents[1] / "static"
MAX_UPLOAD = 5 * 1024 * 1024
ALLOWED_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/webp", "text/plain"}


@asynccontextmanager
async def lifespan(_app):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(title="MedCard AI API", version="1.0.0", lifespan=lifespan)


# ---------------------------------------------------------------- serializers (shape = what the frontend reads)
def e(value):
    """HTML-escape user-supplied text. The UI renders with innerHTML, so a report named
    '<img onerror=...>' would otherwise run inside a doctor's session."""
    return html.escape(value) if isinstance(value, str) else value


def report_out(r: Report) -> dict:
    return {"id": r.id, "name": e(r.name), "date": r.date.isoformat(), "type": e(r.type), "status": r.status,
            "notes": e(r.notes), "added_by": e(r.added_by), "has_file": r.file_data is not None,
            "file_name": e(r.file_name), "ai_summary": e(r.ai_summary)}


UNITS = r"(?:g/dL|mg/dL|mmol/L|ng/mL|mIU/L|µIU/mL|uIU/mL|IU/L|/µL|/uL|bpm|ms|mmHg|L/min|fL|kg/m²|lakh|%)"
VALUE_RE = re.compile(r"([A-Za-z][A-Za-z0-9 ()/-]{1,28}?)[:\s]+(\d[\d.,]*\s?" + UNITS + r")(\s*\((?:high|low|deficient)\)|\s*\((?:HIGH|LOW)\)|\s+(?:HIGH|LOW))?")


def report_values(r: Report) -> list[list[str]]:
    """Test values for the "View Full Report" panel: stored ones, else read from the notes / report text."""
    if r.details:
        try:
            return json.loads(r.details)
        except ValueError:
            pass
    found, seen = [], set()
    for m in VALUE_RE.finditer(f"{r.notes}\n{r.extracted_text}"):
        label = m.group(1).strip(" ,-—").title() if m.group(1).islower() else m.group(1).strip(" ,-—")
        if label.lower() in seen or len(found) >= 8:
            continue
        seen.add(label.lower())
        flagged = bool(m.group(3)) or re.search(r"\b(LOW|HIGH|deficient)\b", r.notes[m.end():m.end() + 14] or "")
        found.append([label, m.group(2).strip() + (" ⚠" if flagged else " ✓"), "warn" if flagged else "ok"])
    return found


def appt_out(a: Appointment) -> dict:
    return {"id": a.id, "date": a.date.isoformat(), "month": a.date.strftime("%b").upper(),
            "day": a.date.strftime("%d"), "doctor": e(a.doctor.user.name), "doctor_id": a.doctor.user.public_id,
            "specialty": e(a.doctor.specialty), "patient": e(a.patient.user.name),
            "patient_id": a.patient.user.public_id, "reason": e(a.reason), "status": a.status}


def vital_out(v: Vital) -> dict:
    return {"recorded_at": v.recorded_at.isoformat(timespec="minutes"), "systolic": v.systolic,
            "diastolic": v.diastolic, "heart_rate": v.heart_rate, "blood_sugar": v.blood_sugar,
            "hemoglobin": v.hemoglobin, "cholesterol": v.cholesterol, "bmi": v.bmi}


def patient_out(p: Patient) -> dict:
    return {"id": p.user.public_id, "name": e(p.user.name), "email": e(p.user.email),
            "dob": p.dob.isoformat() if p.dob else "", "blood": e(p.blood), "phone": e(p.phone),
            "allergies": e(p.allergies or "None"),
            "conditions": [e(c.strip()) for c in (p.conditions or "").split(",") if c.strip()],
            "emergency_contact": e(p.emergency_contact), "card_token": p.card_token,
            "reports": [report_out(r) for r in p.reports],
            "appointments": [appt_out(a) for a in p.appointments],
            "vitals": [vital_out(v) for v in p.vitals]}


def doctor_out(d: Doctor) -> dict:
    return {"id": d.user.public_id, "name": e(d.user.name), "specialty": e(d.specialty), "phone": e(d.phone),
            "email": e(d.user.email)}


def policy_out(p: Policy) -> dict:
    return {"id": p.id, "title": e(p.title), "date": p.date.isoformat(), "status": e(p.status)}


def patient_of(user: User) -> Patient:
    if user.patient is None:
        raise HTTPException(403, "Patient account required")
    return user.patient


def find_patient(db: Session, public_id: str) -> Patient:
    p = db.scalar(select(Patient).join(User).where(User.public_id == public_id))
    if p is None:
        raise HTTPException(404, "Patient not found")
    return p


def can_see_patient(user: User, p: Patient) -> bool:
    return user.role in ("doctor", "admin") or (user.patient is not None and user.patient.id == p.id)


# ---------------------------------------------------------------- auth
class LoginIn(BaseModel):
    role: str = Field(pattern="^(patient|doctor|admin)$")
    identifier: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=128)
    otp: str = Field(default="", max_length=6)
    name: str = Field(default="", max_length=120)


# No SMS provider is wired in, so the OTP is a fixed demo code (change it with LOGIN_OTP).
LOGIN_OTP = os.getenv("LOGIN_OTP", "123456")


class RegisterIn(BaseModel):
    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(min_length=1, max_length=60)
    dob: date
    blood: str = Field(default="O+", max_length=5)
    phone: str = Field(default="", max_length=30)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    allergies: str = Field(default="None", max_length=200)
    conditions: str = Field(default="", max_length=300)


@app.post("/api/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    ident = body.identifier.strip()
    user = db.scalar(select(User).where(User.role == body.role,
                                        or_(User.public_id == ident, func.lower(User.email) == ident.lower())))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong ID/email or password")
    if body.otp.strip() != LOGIN_OTP:
        raise HTTPException(401, f"Invalid OTP. Use demo OTP: {LOGIN_OTP}")
    if body.name.strip() and body.name.strip().lower() not in user.name.lower():
        raise HTTPException(401, "Full name doesn't match this account")
    return {"token": make_token(user), "role": user.role}


@app.post("/api/auth/register", status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if body.dob > date.today():
        raise HTTPException(422, "Date of birth can't be in the future")
    if db.scalar(select(User.id).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(409, "An account with this email already exists")
    # patient IDs keep the 13-digit 250707xxxxxxx format the card design expects
    last = db.scalar(select(func.max(User.public_id)).where(User.role == "patient", User.public_id.like("250707%")))
    next_id = str(int(last) + 1) if last else "2507070000100"
    user = User(public_id=next_id, email=body.email.lower(), name=f"{body.first_name.strip()} {body.last_name.strip()}",
                role="patient", password_hash=hash_password(body.password))
    db.add(Patient(user=user, dob=body.dob, blood=body.blood, phone=body.phone or "—",
                   allergies=body.allergies or "None", conditions=body.conditions))
    db.commit()
    return {"token": make_token(user), "role": "patient", "patient_id": next_id}


# ---------------------------------------------------------------- everything the UI needs after login
@app.get("/api/bootstrap")
def bootstrap(user: User = Depends(current_user), db: Session = Depends(get_db)):
    doctors = [doctor_out(d) for d in db.scalars(select(Doctor))]
    policies = [policy_out(p) for p in db.scalars(select(Policy).order_by(Policy.date.desc()))]
    if user.role == "patient":
        me = patient_out(patient_of(user))
        return {"role": "patient", "user": me, "patients": [me], "doctors": doctors, "policies": policies,
                "ai": ai.provider()}
    patients = [patient_out(p) for p in db.scalars(select(Patient))]
    if user.role == "doctor":
        me = {**doctor_out(user.doctor),
              "appointments": [appt_out(a) for a in sorted(user.doctor.appointments, key=lambda a: a.date)]}
    else:
        me = {"id": user.public_id, "name": e(user.name), "email": e(user.email)}
    return {"role": user.role, "user": me, "patients": patients, "doctors": doctors, "policies": policies,
            "ai": ai.provider()}


# ---------------------------------------------------------------- reports
def extract_text(data: bytes, content_type: str) -> str:
    try:
        if content_type == "application/pdf":
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((page.extract_text() or "") for page in reader.pages[:10])[:20000]
        if content_type == "text/plain":
            return data.decode("utf-8", errors="ignore")[:20000]
    except Exception:
        return ""
    return ""  # images: the AI reads them directly at analysis time


@app.post("/api/reports/upload", status_code=201)
async def upload_report(file: UploadFile = File(...), name: str = Form(""), type: str = Form("Lab"),
                        user: User = Depends(require("patient")), db: Session = Depends(get_db)):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(415, "Upload a PDF, image (PNG/JPG/WEBP) or text file")
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File is larger than 5 MB")
    p = patient_of(user)
    text = extract_text(data, file.content_type)
    title = (name or Path(file.filename or "Report").stem).strip()[:150]
    r = Report(patient=p, name=title, type=type[:40], status="Pending", file_name=file.filename,
               file_type=file.content_type, file_data=data, extracted_text=text, added_by=user.name,
               notes=(text[:280].replace("\n", " ").strip() or "Uploaded — AI analysis pending"))
    db.add(r)
    db.commit()
    return report_out(r)


class DoctorReportIn(BaseModel):
    patient_id: str
    name: str = Field(min_length=1, max_length=150)
    type: str = Field(default="Lab", max_length=40)
    status: str = Field(default="Normal", pattern="^(Normal|Abnormal|Review|Pending)$")
    notes: str = Field(default="", max_length=5000)


@app.post("/api/reports", status_code=201)
def add_report(body: DoctorReportIn, user: User = Depends(require("doctor", "admin")), db: Session = Depends(get_db)):
    p = find_patient(db, body.patient_id)
    r = Report(patient=p, name=body.name, type=body.type, status=body.status, notes=body.notes, added_by=user.name)
    db.add(r)
    db.commit()
    return report_out(r)


def get_report(db: Session, report_id: int, user: User) -> Report:
    r = db.get(Report, report_id)
    if r is None or not can_see_patient(user, r.patient):
        raise HTTPException(404, "Report not found")
    return r


@app.get("/api/reports/{report_id}/file")
def report_file(report_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = get_report(db, report_id, user)
    if r.file_data is None:
        raise HTTPException(404, "No file attached to this report")
    return Response(r.file_data, media_type=r.file_type,
                    headers={"Content-Disposition": f'inline; filename="{r.file_name}"'})


@app.post("/api/reports/{report_id}/analyze")
def analyze_report(report_id: int, user: User = Depends(current_user), db: Session = Depends(get_db),
                   x_ai_key: str | None = Header(default=None)):
    r = get_report(db, report_id, user)
    p = r.patient
    content = f"\n\nFULL REPORT TEXT:\n{r.extracted_text[:8000]}" if r.extracted_text else ""
    prompt = (f'Analyze this medical report: "{r.name}" (Type: {r.type}, Status: {r.status}, '
              f"Notes: {r.notes}). Patient blood type: {p.blood}, Conditions: {p.conditions or 'None'}, "
              f"Allergies: {p.allergies or 'None'}.{content}\n\n"
              "Provide a structured analysis with these sections:\n\n📋 SUMMARY\n(2-3 sentences in plain language)"
              "\n\n🔍 KEY FINDINGS\n• (important values/observations, quote actual numbers)"
              "\n\n⚠️ CONCERNS\n• (anything needing attention, or \"None identified\")"
              "\n\n✅ RECOMMENDATIONS\n• (2-3 actionable next steps)"
              "\n\nKeep it clear, warm, and patient-friendly. Do not diagnose — recommend consulting their doctor.")
    image = (r.file_data, r.file_type) if r.file_type and r.file_type.startswith("image/") else None
    try:
        text = ai.complete(user.id, prompt, image=image, api_key=x_ai_key)
    except ai.RateLimited:
        raise HTTPException(429, "AI limit reached for this hour")
    except ai.AIUnavailable:
        raise HTTPException(503, "AI_OFFLINE")
    r.ai_summary = text
    if r.status == "Pending":
        r.status = "Review"
    db.commit()
    return {"report": report_out(r), "analysis": e(text)}


# ---------------------------------------------------------------- appointments
class AppointmentIn(BaseModel):
    doctor_id: str
    date: date
    reason: str = Field(default="", max_length=200)


@app.post("/api/appointments", status_code=201)
def book(body: AppointmentIn, user: User = Depends(require("patient")), db: Session = Depends(get_db)):
    if body.date < date.today():
        raise HTTPException(422, "Pick today or a future date")
    doctor = db.scalar(select(Doctor).join(User).where(User.public_id == body.doctor_id))
    if doctor is None:
        raise HTTPException(404, "Doctor not found")
    p = patient_of(user)
    clash = db.scalar(select(Appointment.id).where(Appointment.patient_id == p.id, Appointment.doctor_id == doctor.id,
                                                   Appointment.date == body.date, Appointment.status == "Upcoming"))
    if clash:
        raise HTTPException(409, "You already have an appointment with this doctor on that day")
    a = Appointment(patient=p, doctor=doctor, date=body.date, reason=body.reason)
    db.add(a)
    db.commit()
    return appt_out(a)


class AppointmentStatusIn(BaseModel):
    status: str = Field(pattern="^(Upcoming|Completed|Cancelled)$")


@app.patch("/api/appointments/{appt_id}")
def update_appointment(appt_id: int, body: AppointmentStatusIn, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    a = db.get(Appointment, appt_id)
    if a is None:
        raise HTTPException(404, "Appointment not found")
    is_owner_patient = user.patient is not None and a.patient_id == user.patient.id
    is_its_doctor = user.doctor is not None and a.doctor_id == user.doctor.id
    if not (is_its_doctor or user.role == "admin" or (is_owner_patient and body.status == "Cancelled")):
        raise HTTPException(403, "You can't change this appointment")
    a.status = body.status
    db.commit()
    return appt_out(a)


# ---------------------------------------------------------------- vitals
class VitalIn(BaseModel):
    systolic: float | None = Field(default=None, ge=50, le=260)
    diastolic: float | None = Field(default=None, ge=30, le=180)
    heart_rate: float | None = Field(default=None, ge=25, le=250)
    blood_sugar: float | None = Field(default=None, ge=1, le=40)
    hemoglobin: float | None = Field(default=None, ge=3, le=25)
    cholesterol: float | None = Field(default=None, ge=50, le=600)
    bmi: float | None = Field(default=None, ge=10, le=80)


@app.post("/api/vitals", status_code=201)
def log_vitals(body: VitalIn, user: User = Depends(require("patient")), db: Session = Depends(get_db)):
    values = body.model_dump()
    if all(v is None for v in values.values()):
        raise HTTPException(422, "Enter at least one reading")
    v = Vital(patient=patient_of(user), **values)
    db.add(v)
    db.commit()
    return vital_out(v)


# ---------------------------------------------------------------- policies (admin)
class PolicyIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    status: str = Field(default="Active", max_length=30)


@app.post("/api/policies", status_code=201)
def add_policy(body: PolicyIn, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    p = Policy(title=body.title.strip(), status=body.status)
    db.add(p)
    db.commit()
    return policy_out(p)


# ---------------------------------------------------------------- AI
class AIIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)
    system: str | None = Field(default=None, max_length=4000)
    history: list[dict] = Field(default_factory=list, max_length=30)


@app.post("/api/ai/complete")
def ai_complete(body: AIIn, user: User = Depends(current_user),
                x_ai_key: str | None = Header(default=None)):
    try:
        return {"text": ai.complete(user.id, body.prompt, body.system, body.history, api_key=x_ai_key)}
    except ai.RateLimited:
        raise HTTPException(429, "AI limit reached for this hour")
    except ai.AIUnavailable:
        raise HTTPException(503, "AI_OFFLINE")


# ---------------------------------------------------------------- QR + public emergency card
@app.get("/api/qr.png")
def qr_png(data: str, size: int = 8):
    if len(data) > 500:
        raise HTTPException(422, "QR data too long")
    qr = qrcode.QRCode(border=2, box_size=max(2, min(size, 12)), error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    img = qr.make_image(fill_color="#4A0E1A", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/public/card/{token}")
def public_card(token: str, db: Session = Depends(get_db)):
    """Emergency view: medically useful, no name / phone / ID (anonymized by design)."""
    p = db.scalar(select(Patient).where(Patient.card_token == token))
    if p is None:
        raise HTTPException(404, "This card link is invalid or was reset by its owner")
    return {"blood": e(p.blood), "allergies": e(p.allergies or "None"),
            "conditions": [e(c.strip()) for c in (p.conditions or "").split(",") if c.strip()],
            "emergency_contact": e(p.emergency_contact),
            "reports": [{"name": e(r.name), "date": r.date.isoformat(), "type": e(r.type), "status": r.status,
                         "notes": e(r.notes), "ai_summary": e(r.ai_summary),
                         # a doctor's name is fine; the patient's own name would break the anonymity
                         "added_by": "" if r.added_by == p.user.name else e(r.added_by),
                         "values": [[e(a), e(b), f if f in ("ok", "warn", "bad") else "ok"] for a, b, f in report_values(r)],
                         "conclusion": e(r.conclusion), "conclusion_flag": r.conclusion_flag}
                        for r in sorted(p.reports, key=lambda r: r.date, reverse=True)]}


@app.post("/api/card/regenerate")
def regenerate_card(user: User = Depends(require("patient")), db: Session = Depends(get_db)):
    p = patient_of(user)
    p.card_token = new_card_token()  # old QR codes stop working immediately
    db.commit()
    return {"card_token": p.card_token}


class ProfileIn(BaseModel):
    phone: str | None = Field(default=None, max_length=30)
    allergies: str | None = Field(default=None, max_length=200)
    conditions: str | None = Field(default=None, max_length=300)
    emergency_contact: str | None = Field(default=None, max_length=120)


@app.patch("/api/me")
def update_profile(body: ProfileIn, user: User = Depends(require("patient")), db: Session = Depends(get_db)):
    p = patient_of(user)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(p, k, v.strip())
    db.commit()
    return patient_out(p)


# ---------------------------------------------------------------- health + frontend
@app.get("/api/health")
def health():
    return {"status": "ok", "ai": ai.provider(), "time": utcnow().isoformat(timespec="seconds")}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")
