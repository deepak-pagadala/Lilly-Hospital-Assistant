# app/crud.py

from sqlalchemy.orm import Session
from . import models, schemas

def get_doctors(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Doctor).offset(skip).limit(limit).all()

def get_doctor(db: Session, doctor_id: int):
    return db.query(models.Doctor).filter(models.Doctor.id == doctor_id).first()

def get_doctor_slots(db: Session, doctor_id: int):
    return db.query(models.Slot).filter(models.Slot.doctor_id == doctor_id, models.Slot.is_booked == False).all()

def create_appointment(db: Session, appointment: schemas.AppointmentCreate):
    slot = db.query(models.Slot).filter(models.Slot.id == appointment.slot_id, models.Slot.is_booked == False).first()
    if not slot:
        print(f"[DEBUG] Slot not found or already booked: {appointment.slot_id}")
        return None
    slot.is_booked = True
    db_appointment = models.Appointment(
        doctor_id=appointment.doctor_id,
        slot_id=appointment.slot_id,
        patient_name=appointment.patient_name,
        status="booked"
    )
    db.add(db_appointment)
    db.commit()
    db.refresh(db_appointment)
    print(f"[DEBUG] Created appointment: {db_appointment}")
    return db_appointment