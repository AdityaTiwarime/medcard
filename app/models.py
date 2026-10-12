import secrets
from datetime import date, datetime, timezone

from sqlalchemy import (Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String,
                        Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_card_token() -> str:
    return secrets.token_urlsafe(18)


class User(Base):
    """One login. role is patient / doctor / admin; profile rows hang off it."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # 2507070000057, DR001, SA001
    email: Mapped[str | None] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(10), index=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    patient: Mapped["Patient | None"] = relationship(back_populates="user", uselist=False)
    doctor: Mapped["Doctor | None"] = relationship(back_populates="user", uselist=False)


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    dob: Mapped[date | None] = mapped_column(Date)
    blood: Mapped[str] = mapped_column(String(5), default="—")
    phone: Mapped[str] = mapped_column(String(30), default="—")
    allergies: Mapped[str] = mapped_column(String(200), default="None")
    conditions: Mapped[str] = mapped_column(String(300), default="")  # comma separated
    emergency_contact: Mapped[str] = mapped_column(String(120), default="")
    card_token: Mapped[str] = mapped_column(String(40), unique=True, index=True, default=new_card_token)

    user: Mapped[User] = relationship(back_populates="patient")
    reports: Mapped[list["Report"]] = relationship(back_populates="patient", order_by="Report.date.desc()",
                                                   cascade="all, delete-orphan")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="patient",
                                                             order_by="Appointment.date",
                                                             cascade="all, delete-orphan")
    vitals: Mapped[list["Vital"]] = relationship(back_populates="patient",
                                                 order_by="Vital.recorded_at.desc()",
                                                 cascade="all, delete-orphan")


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    specialty: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(30), default="—")

    user: Mapped[User] = relationship(back_populates="doctor")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="doctor")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    date: Mapped[date] = mapped_column(Date, default=date.today)
    type: Mapped[str] = mapped_column(String(40), default="Lab")
    status: Mapped[str] = mapped_column(String(20), default="Pending")
    notes: Mapped[str] = mapped_column(Text, default="")
    added_by: Mapped[str] = mapped_column(String(120), default="")
    file_name: Mapped[str | None] = mapped_column(String(200))
    file_type: Mapped[str | None] = mapped_column(String(80))
    file_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    ai_summary: Mapped[str] = mapped_column(Text, default="")
    # "View Full Report" panel on the QR page: JSON [[label, value, "ok"|"warn"|"bad"], ...] + doctor's note
    details: Mapped[str] = mapped_column(Text, default="")
    conclusion: Mapped[str] = mapped_column(Text, default="")
    conclusion_flag: Mapped[str] = mapped_column(String(8), default="ok")

    patient: Mapped[Patient] = relationship(back_populates="reports")


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), index=True)
    date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="Upcoming")  # Upcoming / Completed / Cancelled

    patient: Mapped[Patient] = relationship(back_populates="appointments")
    doctor: Mapped[Doctor] = relationship(back_populates="appointments")


class Vital(Base):
    __tablename__ = "vitals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    systolic: Mapped[float | None] = mapped_column(Float)
    diastolic: Mapped[float | None] = mapped_column(Float)
    heart_rate: Mapped[float | None] = mapped_column(Float)
    blood_sugar: Mapped[float | None] = mapped_column(Float)   # mmol/L
    hemoglobin: Mapped[float | None] = mapped_column(Float)    # g/dL
    cholesterol: Mapped[float | None] = mapped_column(Float)   # mg/dL
    bmi: Mapped[float | None] = mapped_column(Float)

    patient: Mapped[Patient] = relationship(back_populates="vitals")


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    date: Mapped[date] = mapped_column(Date, default=date.today)
    status: Mapped[str] = mapped_column(String(30), default="Active")
