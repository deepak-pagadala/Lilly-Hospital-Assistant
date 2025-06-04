from sqlalchemy import create_engine, text
engine = create_engine("postgresql+psycopg2://hospital_ai:hospital_ai_pass@localhost:5432/hospital_ai")
conn = engine.connect()
result = conn.execute(text("SELECT * FROM doctors;"))
print(result.fetchall())
conn.close()
