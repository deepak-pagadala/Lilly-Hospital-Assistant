import os
import json
import base64
import asyncio
import websockets
import datetime
from io import BytesIO
from dotenv import load_dotenv
import openai
from fastapi import FastAPI, WebSocket, Request, Depends, HTTPException, Query, File, UploadFile, Response, APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session
from . import models, schemas, crud
from .database import SessionLocal, engine, Base
from .schemas import ChatRequest
from fastapi.staticfiles import StaticFiles

# --------------- Logging Setup ---------------
LOGFILE = "app_run.log"
def log(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOGFILE, "a") as f:
        f.write(f"{timestamp} {msg}\n")

# --- Config ---
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
VOICE = "alloy"
NGROK_BASE = "https://e297-2600-1702-7d20-1790-30e1-c873-c7d4-ee3e.ngrok-free.app"  # <-- Set your ngrok https URL here!
SYSTEM_MESSAGE = (
    "You are Lilly, a helpful, empathetic hospital assistant at Rock Hospitals. "
    "You always start your conversation with a greeting."
    "When you need real data (doctor list, open slots, booking, cancelling) you MUST call the tool that does it. "
+   "NEVER make up doctors, slots or IDs, always use the function responses. "
    "Use natural conversation, hesitations, and warmth. Help users with doctors, appointments, etc. "
    "Ask clarifying questions, suggest slots, and never book until user confirms. Never provide medical advice."
    "say only one sentence at once, don't rush."
)
app = FastAPI(
    title="Hospital AI Voice Assistant API",
    description="API for doctors, slots, and appointment booking",
    version="0.2.0"
)
router = APIRouter()


# --- DB Setup ---
Base.metadata.create_all(bind=engine)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Conversation store for Twilio calls ---
CONV_HISTORY = {}

# --- Classic REST endpoints (for your admin/app frontend) ---
@app.get("/doctors", response_model=list[schemas.DoctorBase])
def read_doctors(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    log(f"/doctors called: skip={skip}, limit={limit}")
    return crud.get_doctors(db, skip=skip, limit=limit)

@app.get("/doctors/{doctor_id}/slots", response_model=list[schemas.SlotBase])
def read_doctor_slots(doctor_id: int, db: Session = Depends(get_db)):
    log(f"/doctors/{doctor_id}/slots called")
    return crud.get_doctor_slots(db, doctor_id)

@app.get("/appointments", response_model=list[schemas.AppointmentBase])
def get_all_appointments(db: Session = Depends(get_db)):
    appointments = db.query(models.Appointment).all()
    print(f"[DEBUG] Appointments in DB: {appointments}")
    return appointments


@app.post("/appointments", response_model=schemas.AppointmentBase)
def create_appointment(appointment: schemas.AppointmentCreate, db: Session = Depends(get_db)):
    log(f"/appointments called: {appointment}")
    db_appointment = crud.create_appointment(db, appointment)
    if not db_appointment:
        log(f"Slot not available for {appointment}")
        raise HTTPException(status_code=400, detail="Slot not available")
    return db_appointment

@app.post("/tts")
async def tts_endpoint(
    text: str = Query(..., description="Text to convert to speech"),
    voice: str = Query(VOICE, description="Voice to use: alloy, echo, fable, onyx, nova, shimmer")
):
    log(f"/tts called: text='{text[:30]}...' voice='{voice}'")
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    try:
        response = client.audio.speech.create(
            model="tts-1", voice=voice, input=text, response_format="mp3"
        )
        audio_data = BytesIO(response.content)
        return StreamingResponse(audio_data, media_type="audio/mpeg")
    except Exception as e:
        log(f"/tts error: {e}")
        return {"error": str(e)}

@app.post("/stt")
def stt_endpoint(audio: UploadFile = File(...), language: str = "en"):
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    audio.file.seek(0)
    audio_bytes = audio.file.read()
    log(f"/stt called for file: {audio.filename}")
    try:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=(audio.filename, audio_bytes, audio.content_type),
            language=language
        )
        return {"text": transcript.text}
    except Exception as e:
        log(f"/stt error: {e}")
        return JSONResponse(status_code=400, content={"error": str(e)})

# --- Twilio incoming call: give TwiML that points to websocket ---
@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    from twilio.twiml.voice_response import VoiceResponse, Connect
    response = VoiceResponse()
    response.say("Connecting you, please stay on line.")
    connect = Connect()
    # Ensure no double protocol!
    ws_url = f"wss://e297-2600-1702-7d20-1790-30e1-c873-c7d4-ee3e.ngrok-free.app/media-stream"
    connect.stream(url=ws_url)
    response.append(connect)
    log(f"Twilio incoming-call: returned TwiML with stream to {ws_url}")
    return Response(content=str(response), media_type="application/xml")

@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    await websocket.accept()
    log("WebSocket: connection opened")
    db = SessionLocal()

    openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
    stream_sid = None

    function_list = [
        {
            "type": "function",
            "name": "list_doctors",
            "description": "Get a list of doctors by specialty.",
            "parameters": {
                "type": "object",
                "properties": {
                    "specialty": {
                        "type": "string",
                        "description": "Specialty of the doctor, e.g., 'cardiologist', 'pediatrician'."
                    }
                },
                "required": ["specialty"]
            }
        },
        {
            "type": "function",
            "name": "cancel_appointment",
            "description": "Cancel an appointment by appointment ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_id": {"type": "integer"}
                },
                "required": ["appointment_id"]
            }
        },
        {
            "type": "function",
            "name": "list_slots",
            "description": "List available slots for a given doctor and optional date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doctor_id": {"type": "integer"},
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD format (optional)"}
                },
                "required": ["doctor_id"]
            }
        },
        {
            "type": "function",
            "name": "book_appointment",
            "description": "Book an appointment for a user with a doctor at a given slot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doctor_id": {"type": "integer"},
                    "slot_id": {"type": "integer"},
                    "patient_name": {"type": "string"}
                },
                "required": ["doctor_id", "slot_id", "patient_name"]
            }
        }
    ]

    async with websockets.connect(
        'wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01',
        additional_headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1"
        }
    ) as openai_ws:
        await openai_ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "turn_detection": {"type": "server_vad"},
                "input_audio_format": "g711_ulaw",
                "output_audio_format": "g711_ulaw",
                "voice": VOICE,
                "instructions": SYSTEM_MESSAGE,
                "modalities": ["text", "audio"],
                "temperature": 0.6,
                "tools": function_list,
            }
        }))
        log("OpenAI session started.")
        await openai_ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "The phone is ringing. You pick up. Greet the caller and ask how you can help."}]
            }
        }))
        await openai_ws.send(json.dumps({"type": "response.create"}))
        stream_sid_holder = {"sid": None}

        async def receive_from_twilio():
            async for message in websocket.iter_text():
                log(f"FROM_TWILIO: {message[:200]}")
                data = json.loads(message)
                event_type = data.get('event')
                if event_type == 'start':
                    stream_sid_holder['sid'] = data['start']['streamSid']
                    log(f"Twilio stream started: {stream_sid_holder['sid']}")
                elif event_type == 'media':
                    audio_append = {
                        "type": "input_audio_buffer.append",
                        "audio": data['media']['payload']
                    }
                    await openai_ws.send(json.dumps(audio_append))
                elif event_type == 'stop':
                    log(f"Twilio stream stopped: {stream_sid_holder['sid']}")
                    break

        async def send_to_twilio():
            while True:
                openai_message = await openai_ws.recv()
                log(f"FROM_OPENAI: {openai_message[:200]}")
                response = json.loads(openai_message)

                if response.get("type") == "function_call":
                    fn = response["function_call"]
                    fn_name = fn["name"]
                    fn_args = fn["arguments"]
                    result = {}
                    print(f"[DEBUG] Function call received: {fn_name}")
                    print(f"[DEBUG] Arguments: {fn_args}")

                    try:
                        if fn_name == "list_doctors":
                            specialty = fn_args.get("specialty", "")
                            print(f"[DEBUG] Requested doctor specialty: {specialty}")
                            doctors = db.query(models.Doctor).filter(models.Doctor.specialty.ilike(f"%{specialty}%")).all()
                            result = [
                                {"id": d.id, "name": d.name, "specialty": d.specialty, "contact_info": d.contact_info}
                                for d in doctors
                            ]
                        elif fn_name == "list_slots":
                            doctor_id = fn_args["doctor_id"]
                            date = fn_args.get("date")
                            query = db.query(models.Slot).filter(
                                models.Slot.doctor_id == doctor_id,
                                models.Slot.is_booked == False
                            )
                            if date:
                                from datetime import datetime
                                day_start = datetime.fromisoformat(date)
                                day_end = day_start.replace(hour=23, minute=59, second=59)
                                query = query.filter(
                                    models.Slot.start_time >= day_start,
                                    models.Slot.start_time <= day_end
                                )
                            slots = query.all()
                            result = [
                                {"id": s.id, "start_time": str(s.start_time)}
                                for s in slots
                            ]
                        elif fn_name == "cancel_appointment":
                            appt_id = fn_args["appointment_id"]
                            appt = db.query(models.Appointment).filter(models.Appointment.id == appt_id).first()
                            if appt:
                                db.delete(appt)
                                db.commit()
                                result = {"success": True}
                            else:
                                result = {"success": False, "reason": "Appointment not found"}
                        elif fn_name == "book_appointment":
                            doctor_id = fn_args["doctor_id"]
                            slot_id = fn_args["slot_id"]
                            patient_name = fn_args["patient_name"]
                            print(f"[DEBUG] Booking appointment: doctor_id={doctor_id}, slot_id={slot_id}, patient_name={patient_name}")
                            log(f"Booking appointment with doctor_id={doctor_id}, slot_id={slot_id}, patient_name={patient_name}")
                            log(f"Appointment object: {appointment}")

                            try:
                                appointment = crud.create_appointment(
                                    db, schemas.AppointmentCreate(
                                        doctor_id=doctor_id,
                                        slot_id=slot_id,
                                        patient_name=patient_name
                                    )
                                )
                                if appointment:
                                    db.commit()
                                    result = {
                                        "success": True,
                                        "appointment_id": appointment.id,
                                        "doctor_id": doctor_id,
                                        "slot_id": slot_id
                                    }
                                else:
                                    result = {"success": False, "reason": "Slot not available"}
                            except Exception as ex:
                                db.rollback()
                                result = {"error": str(ex)}
                    except Exception as ex:
                        result = {"error": str(ex)}
                    log(f"Function {fn_name} called with {fn_args}, result={result}")
                    await openai_ws.send(json.dumps({
                        "type": "conversation.item.create",
                        "item": {
                            "type": "function",
                            "name": fn_name,
                            "content": json.dumps(result)
                        }
                    }))

                if response.get("type") == "response.audio.delta" and "delta" in response:
                    stream_sid = stream_sid_holder["sid"]
                    if stream_sid:
                        audio_payload = response["delta"]
                        await websocket.send_json({
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {
                                "track": "outbound",
                                "payload": audio_payload
                            }
                        })

        try:
            await asyncio.gather(receive_from_twilio(), send_to_twilio())
        except Exception as e:
            log(f"WebSocket session closed with error: {e}")
        finally:
            db.close()
            log("WebSocket: connection closed")

# --- Classic /chat endpoint for frontend/testing ---
@router.post("/chat")
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    messages = [msg.dict(exclude_unset=True) for msg in request.messages]
    if messages[0]["role"] != "system":
        system_prompt = {
            "role": "system",
            "content": SYSTEM_MESSAGE
        }
        messages = [system_prompt] + messages
    FUNCTION_LIST = [
        # (Same as above)
    ]
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    try:
        response = client.chat.completions.create(
            model="gpt-4-0613",
            messages=messages,
            functions=FUNCTION_LIST,
            function_call="auto",
            max_tokens=256,
            temperature=0.6
        )
        first_choice = response.choices[0]
        if first_choice.finish_reason == "function_call":
            fn = first_choice.message.function_call
            fn_name = fn.name
            fn_args = json.loads(fn.arguments)
            # Handle like in /media-stream above (copy logic)
            # Return function result
        return {"reply": first_choice.message.content}
    except Exception as e:
        log(f"/chat error: {e}")
        return {"error": str(e)}

app.include_router(router)