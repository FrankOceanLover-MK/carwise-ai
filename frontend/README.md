# Carwise AI — Streamlit Frontend

This Streamlit app talks to your local FastAPI backend.

## Prereqs
Run backend (from repo root):
```
uvicorn app.main:app --reload
```
Expected endpoints:
- GET /health
- GET /cars/{vin}
- GET /cars/{vin}/summary
- (optional) GET /recommendations or GET /cars/recommendations

## Setup
```
cd frontend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run
```
# Backend URL defaults to http://127.0.0.1:8000
streamlit run streamlit_app.py
```

Override backend URL:
```
BACKEND_BASE_URL=http://localhost:8000 streamlit run streamlit_app.py
```
