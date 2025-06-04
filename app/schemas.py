# app/schemas.py

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class SlotBase(BaseModel):
    id: int
    start_time: datetime
    is_booked: bool

    class Config:
        orm_mode = True

class DoctorBase(BaseModel):
    id: int
    name: str
    specialty: str
    description: Optional[str] = None
    contact_info: Optional[str] = None
    # For listing slots with doctor (optional)
    slots: Optional[List[SlotBase]] = None

    class Config:
        from_attributes = True


class AppointmentBase(BaseModel):
    id: int
    doctor_id: int
    slot_id: int
    patient_name: str
    status: str
    created_at: datetime

    class Config:
        orm_mode = True

# Schemas for creating new appointments (requests)
class AppointmentCreate(BaseModel):
    doctor_id: int
    slot_id: int
    patient_name: str

class ChatMessage(BaseModel):
    role: str  
    content: str
    name: Optional[str] = None  

class ChatRequest(BaseModel):
    messages: List[ChatMessage]