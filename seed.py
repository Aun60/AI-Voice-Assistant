"""Seed the database with 2 demo patients. Run: python seed.py"""
from datetime import date
from app.database import SessionLocal, Base, engine
from app.models import Patient

Base.metadata.create_all(bind=engine)
db = SessionLocal()

seed_patients = [
    Patient(
        first_name="Maria", last_name="Gonzalez", date_of_birth=date(1985, 3, 22),
        sex="Female", phone_number="4155550101", email="maria.g@example.com",
        address_line_1="482 Oak Street", city="Oakland", state="CA", zip_code="94612",
        insurance_provider="Kaiser Permanente", insurance_member_id="KP1234567",
        preferred_language="English",
    ),
    Patient(
        first_name="David", last_name="Chen", date_of_birth=date(1978, 11, 9),
        sex="Male", phone_number="4155550102", email=None,
        address_line_1="19 Pine Ave", address_line_2="Unit 4B", city="San Jose",
        state="CA", zip_code="95112", preferred_language="Mandarin",
    ),
]

for p in seed_patients:
    existing = db.query(Patient).filter(Patient.phone_number == p.phone_number).first()
    if not existing:
        db.add(p)

db.commit()
db.close()
print("Seed complete.")
