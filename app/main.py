import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Patient
from app.schemas import PatientCreate, PatientUpdate, PatientOut, normalize_phone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("patient-registration")

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Patient Registration API", version="1.0.0")


def envelope(data=None, error=None):
    return {"data": data, "error": error}


def _safe_errors(exc):
    # exc.errors() can contain non-JSON-serializable objects (e.g. the raw
    # ValueError/exception instance under "ctx") when custom validators raise.
    # Strip "ctx" (which holds the raw exception object) and stringify the rest.
    cleaned = []
    for err in exc.errors():
        err = dict(err)
        err.pop("ctx", None)
        cleaned.append(err)
    return jsonable_encoder(cleaned)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(status_code=422, content=envelope(error={"message": "Validation error", "details": _safe_errors(exc)}))


@app.exception_handler(ValidationError)
async def pydantic_validation_handler(request, exc):
    return JSONResponse(status_code=422, content=envelope(error={"message": "Validation error", "details": _safe_errors(exc)}))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    logger.exception("Unhandled error")
    return JSONResponse(status_code=500, content=envelope(error={"message": "Internal server error"}))


@app.get("/health")
def health():
    return envelope(data={"status": "ok"})


@app.get("/patients")
def list_patients(
    last_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    phone_number: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Patient).filter(Patient.deleted_at.is_(None))
    if last_name:
        q = q.filter(Patient.last_name.ilike(last_name))
    if date_of_birth:
        q = q.filter(Patient.date_of_birth == date_of_birth)
    if phone_number:
        try:
            q = q.filter(Patient.phone_number == normalize_phone(phone_number))
        except ValueError as e:
            return JSONResponse(status_code=400, content=envelope(error={"message": str(e)}))
    patients = q.order_by(Patient.created_at.desc()).all()
    return envelope(data=[PatientOut.model_validate(p).model_dump(mode="json") for p in patients])


@app.get("/patients/{patient_id}")
def get_patient(patient_id: str, db: Session = Depends(get_db)):
    try:
        pid = uuid.UUID(patient_id)
    except ValueError:
        return JSONResponse(status_code=400, content=envelope(error={"message": "Invalid patient_id format"}))
    patient = db.query(Patient).filter(Patient.patient_id == pid, Patient.deleted_at.is_(None)).first()
    if not patient:
        return JSONResponse(status_code=404, content=envelope(error={"message": "Patient not found"}))
    return envelope(data=PatientOut.model_validate(patient).model_dump(mode="json"))


@app.post("/patients", status_code=201)
def create_patient(payload: PatientCreate, db: Session = Depends(get_db)):
    data = payload.model_dump(exclude_unset=False)
    patient = Patient(**data)
    db.add(patient)
    db.commit()
    db.refresh(patient)
    logger.info("Created patient %s | payload=%s", patient.patient_id, data)
    return envelope(data=PatientOut.model_validate(patient).model_dump(mode="json"))


@app.put("/patients/{patient_id}")
def update_patient(patient_id: str, payload: PatientUpdate, db: Session = Depends(get_db)):
    try:
        pid = uuid.UUID(patient_id)
    except ValueError:
        return JSONResponse(status_code=400, content=envelope(error={"message": "Invalid patient_id format"}))
    patient = db.query(Patient).filter(Patient.patient_id == pid, Patient.deleted_at.is_(None)).first()
    if not patient:
        return JSONResponse(status_code=404, content=envelope(error={"message": "Patient not found"}))

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(patient, field, value)
    patient.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(patient)
    logger.info("Updated patient %s | fields=%s", patient.patient_id, list(updates.keys()))
    return envelope(data=PatientOut.model_validate(patient).model_dump(mode="json"))


@app.delete("/patients/{patient_id}")
def delete_patient(patient_id: str, db: Session = Depends(get_db)):
    try:
        pid = uuid.UUID(patient_id)
    except ValueError:
        return JSONResponse(status_code=400, content=envelope(error={"message": "Invalid patient_id format"}))
    patient = db.query(Patient).filter(Patient.patient_id == pid, Patient.deleted_at.is_(None)).first()
    if not patient:
        return JSONResponse(status_code=404, content=envelope(error={"message": "Patient not found"}))
    patient.deleted_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("Soft-deleted patient %s", patient.patient_id)
    return envelope(data={"patient_id": str(pid), "deleted": True})


# --- Voice-agent-friendly convenience endpoint ---------------------------------
# Vapi's tool-calling works best with a single lookup-by-phone tool so the agent
# can check for an existing record before deciding whether to create or update.
@app.get("/patients/lookup/by-phone/{phone_number}")
def lookup_by_phone(phone_number: str, db: Session = Depends(get_db)):
    try:
        normalized = normalize_phone(phone_number)
    except ValueError as e:
        return JSONResponse(status_code=400, content=envelope(error={"message": str(e)}))
    patient = db.query(Patient).filter(
        Patient.phone_number == normalized, Patient.deleted_at.is_(None)
    ).first()
    if not patient:
        return envelope(data=None)
    return envelope(data=PatientOut.model_validate(patient).model_dump(mode="json"))
