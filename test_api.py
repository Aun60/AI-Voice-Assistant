"""Basic API tests. Run: pytest test_api.py -v
Uses a separate SQLite file so it doesn't touch your dev/demo database.
"""
import os
os.environ["DATABASE_URL"] = "sqlite:///./test_patients.db"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, engine

VALID_PATIENT = {
    "first_name": "Test",
    "last_name": "Patient",
    "date_of_birth": "1990-01-01",
    "sex": "Other",
    "phone_number": "4155550111",
    "address_line_1": "1 Test St",
    "city": "Testville",
    "state": "CA",
    "zip_code": "94105",
}


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "ok"


def test_create_patient_success():
    r = client.post("/patients", json=VALID_PATIENT)
    assert r.status_code == 201
    body = r.json()
    assert body["error"] is None
    assert body["data"]["first_name"] == "Test"
    assert body["data"]["phone_number"] == "4155550111"
    assert "patient_id" in body["data"]


def test_create_patient_missing_required_field():
    payload = dict(VALID_PATIENT)
    del payload["last_name"]
    r = client.post("/patients", json=payload)
    assert r.status_code == 422


def test_create_patient_future_dob_rejected():
    payload = dict(VALID_PATIENT, date_of_birth="2099-01-01")
    r = client.post("/patients", json=payload)
    assert r.status_code == 422


def test_create_patient_invalid_phone_rejected():
    payload = dict(VALID_PATIENT, phone_number="123")
    r = client.post("/patients", json=payload)
    assert r.status_code == 422


def test_create_patient_invalid_state_rejected():
    payload = dict(VALID_PATIENT, state="ZZ")
    r = client.post("/patients", json=payload)
    assert r.status_code == 422


def test_get_patient_by_id():
    created = client.post("/patients", json=VALID_PATIENT).json()["data"]
    r = client.get(f"/patients/{created['patient_id']}")
    assert r.status_code == 200
    assert r.json()["data"]["patient_id"] == created["patient_id"]


def test_get_patient_not_found():
    r = client.get("/patients/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_update_patient_partial():
    created = client.post("/patients", json=VALID_PATIENT).json()["data"]
    r = client.put(f"/patients/{created['patient_id']}", json={"email": "test@example.com"})
    assert r.status_code == 200
    assert r.json()["data"]["email"] == "test@example.com"
    # unchanged field stays the same
    assert r.json()["data"]["first_name"] == "Test"


def test_soft_delete_then_404():
    created = client.post("/patients", json=VALID_PATIENT).json()["data"]
    r = client.delete(f"/patients/{created['patient_id']}")
    assert r.status_code == 200
    r2 = client.get(f"/patients/{created['patient_id']}")
    assert r2.status_code == 404


def test_lookup_by_phone_found_and_not_found():
    client.post("/patients", json=VALID_PATIENT)
    r = client.get(f"/patients/lookup/by-phone/{VALID_PATIENT['phone_number']}")
    assert r.status_code == 200
    assert r.json()["data"]["first_name"] == "Test"

    r2 = client.get("/patients/lookup/by-phone/4155559999")
    assert r2.status_code == 200
    assert r2.json()["data"] is None


def test_list_patients_filter_by_last_name():
    client.post("/patients", json=VALID_PATIENT)
    r = client.get("/patients?last_name=Patient")
    assert r.status_code == 200
    assert len(r.json()["data"]) == 1
