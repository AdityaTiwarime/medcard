"""Demo data so a recruiter can log in and click around immediately. Runs only on an empty database."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Appointment, Doctor, Patient, Policy, Report, User, Vital, utcnow
from .security import hash_password

DEMO_PASSWORD = "Demo@123"


def seed(db: Session):
    if db.scalar(select(User.id).limit(1)):
        return
    pw = hash_password(DEMO_PASSWORD)

    admin = User(public_id="SA001", email="admin@medcard.ai", name="Super Admin", role="admin", password_hash=pw)
    db.add(admin)

    doctors = {}
    for pid, name, spec, phone, email in [
        ("DR001", "Dr. Priya Mehta", "Cardiology", "+91 98000 11001", "priya.mehta@medcard.ai"),
        ("DR002", "Dr. Amit Shah", "General Medicine", "+91 98000 11002", "amit.shah@medcard.ai"),
        ("DR003", "Dr. Kavya Rao", "Pulmonology", "+91 98000 11003", "kavya.rao@medcard.ai"),
    ]:
        u = User(public_id=pid, email=email, name=name, role="doctor", password_hash=pw)
        d = Doctor(user=u, specialty=spec, phone=phone)
        db.add(d)
        doctors[pid] = d

    riya_u = User(public_id="2507070000057", email="riya@example.com", name="Riya Jain", role="patient", password_hash=pw)
    riya = Patient(user=riya_u, dob=date(1999, 3, 15), blood="O+", phone="+91 98765 00057",
                   allergies="None", conditions="Hypertension", emergency_contact="Rakesh Jain · +91 98765 11057")
    riya.reports = [
        Report(name='Blood Count Report', date=date(2026, 3, 10), type='Lab', status='Normal',
               notes='Hemoglobin 13.2 g/dL, WBC 7,400/µL, Platelets 2.1L/µL — all within normal range. No anemia or infection detected.',
               added_by='Dr. Amit Shah', details='[["Hemoglobin", "13.2 g/dL ✓", "ok"], ["WBC Count", "7,400 /µL ✓", "ok"], ["Platelets", "2.1 Lakh ✓", "ok"], ["Neutrophils", "58% ✓", "ok"], ["Hematocrit", "39.8% ✓", "ok"], ["MCV", "86.4 fL ✓", "ok"]]',
               conclusion='Conclusion: All parameters within reference range. Repeat as routine screening in 6 months.', conclusion_flag='ok'),
        Report(name='ECG Report', date=date(2026, 2, 18), type='Cardiac', status='Normal',
               notes='Sinus rhythm 74 bpm. PR 162ms, QRS 88ms, QTc 410ms — all normal. No ST changes or ischemic pattern.',
               added_by='Dr. Priya Mehta', details='[["Heart Rate", "74 bpm ✓", "ok"], ["Rhythm", "Normal Sinus ✓", "ok"], ["QTc Interval", "410 ms ✓", "ok"], ["QRS Duration", "88 ms ✓", "ok"], ["PR Interval", "162 ms ✓", "ok"], ["Axis", "Normal ✓", "ok"]]',
               conclusion='Conclusion: Normal ECG. No arrhythmia, bundle branch block, or myocardial ischemia detected.', conclusion_flag='ok'),
        Report(name='Chest X-Ray', date=date(2026, 1, 22), type='Radiology', status='Review',
               notes='Mild consolidation right lower lobe. Cardiac silhouette normal. No pleural effusion. Follow-up recommended.',
               added_by='Dr. Amit Shah', details='[["Lungs", "Consolidation ⚠", "warn"], ["Cardiac", "Normal ✓", "ok"], ["Pleura", "No Effusion ✓", "ok"], ["Follow-up", "4–6 weeks ⚠", "warn"]]',
               conclusion='⚠ Radiologist Note: Mild RLL consolidation — may be pneumonitis or atelectasis. Clinical correlation advised. Follow-up X-ray recommended.', conclusion_flag='warn'),
        Report(name='Lipid Profile Panel', date=date(2026, 1, 14), type='Biochemistry', status='Abnormal',
               notes='Total cholesterol 224 mg/dL, LDL 148 mg/dL (high), HDL 42 mg/dL (low). Cardiovascular risk elevated.',
               added_by='Dr. Priya Mehta', details='[["Total Cholesterol", "224 mg/dL ⚠", "warn"], ["LDL", "148 mg/dL ✗", "bad"], ["HDL", "42 mg/dL ⚠", "warn"], ["Triglycerides", "188 mg/dL ⚠", "warn"]]',
               conclusion='🔴 Note: Dyslipidemia. Lifestyle modification strongly advised. Consider statin therapy if LDL remains elevated after 3 months.', conclusion_flag='bad'),
        Report(name='Fasting Glucose & HbA1c', date=date(2026, 3, 5), type='Endocrinology', status='Normal',
               notes='Fasting glucose 5.1 mmol/L, HbA1c 5.4% — well within non-diabetic range. No insulin resistance.',
               added_by='Dr. Amit Shah', details='[["Fasting Glucose", "5.1 mmol/L ✓", "ok"], ["HbA1c", "5.4% ✓", "ok"], ["Fasting Insulin", "8.2 µIU/mL ✓", "ok"], ["Status", "Non-Diabetic ✓", "warn"]]',
               conclusion='Conclusion: Excellent glycaemic control. No diabetes or pre-diabetes. Repeat HbA1c annually.', conclusion_flag='ok'),
    ]
    now = utcnow()
    riya.vitals = [
        Vital(recorded_at=now - timedelta(days=30), systolic=134, diastolic=86, heart_rate=80, blood_sugar=5.8,
              hemoglobin=13.0, cholesterol=204, bmi=24.9),
        Vital(recorded_at=now - timedelta(days=2), systolic=128, diastolic=82, heart_rate=76, blood_sugar=5.6,
              hemoglobin=13.2, cholesterol=195, bmi=24.5),
    ]
    db.add(riya)

    diya_u = User(public_id="2507070000080", email="diya@example.com", name="Diya Jain", role="patient", password_hash=pw)
    diya = Patient(user=diya_u, dob=date(2001, 7, 22), blood="A+", phone="+91 98765 00080",
                   allergies="Penicillin", conditions="Asthma, Allergies", emergency_contact="Meena Jain · +91 98765 11080")
    diya.reports = [
        Report(name='Spirometry Test', date=date(2026, 3, 1), type='Pulmonology', status='Abnormal',
               notes='FEV1 72% predicted. FEV1/FVC 0.68 — mild obstructive pattern. Consistent with asthma/early COPD.',
               added_by='Dr. Kavya Rao', details='[["FEV1", "72% ✗", "bad"], ["FVC", "84% ✓", "ok"], ["FEV1/FVC", "0.68 ✗", "bad"], ["Pattern", "Obstructive ✗", "bad"]]',
               conclusion='🔴 Clinical Note: Obstructive airways disease. Bronchodilator reversibility test recommended. Review asthma management plan.', conclusion_flag='bad'),
        Report(name='Allergy Panel', date=date(2026, 2, 10), type='Allergy', status='Normal',
               notes='IgE elevated for dust mites (Class 3) and pollen (Class 2). Penicillin allergy confirmed via skin test.',
               added_by='Dr. Kavya Rao', details='[["Total IgE", "142 IU/mL ⚠", "warn"], ["Dust Mite", "Class 3 ⚠", "warn"], ["Penicillin", "Positive ✗ ALERT", "bad"], ["Food", "Negative ✓", "ok"]]',
               conclusion='🚨 ALLERGY ALERT: Confirmed Penicillin allergy. Avoid all Penicillin-class antibiotics and cross-reactive cephalosporins.', conclusion_flag='bad'),
    ]
    db.add(diya)
    db.flush()

    soon = date.today()
    db.add_all([
        Appointment(patient=riya, doctor=doctors["DR001"], date=soon + timedelta(days=5), reason="BP follow-up"),
        Appointment(patient=riya, doctor=doctors["DR002"], date=soon + timedelta(days=15), reason="Chest X-ray review"),
        Appointment(patient=diya, doctor=doctors["DR003"], date=soon + timedelta(days=8), reason="Asthma review"),
    ])
    db.add_all([
        Policy(title="HIPAA Compliance Update 2026", date=date(2026, 3, 1), status="Active"),
        Policy(title="Telemedicine Service Guidelines", date=date(2026, 2, 15), status="Active"),
        Policy(title="Emergency Data Access Protocol", date=date(2026, 1, 10), status="Under Review"),
    ])
    db.commit()
