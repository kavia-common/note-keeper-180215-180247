# note-keeper-180215-180247

Notes Backend (FastAPI) providing CRUD endpoints.

How to run (container runs on port 3001):
- The environment starts uvicorn for the FastAPI app under `notes_backend/src/api/main.py`.
- Open API docs at: http://localhost:3001/docs
- Health: GET http://localhost:3001/health

Endpoints:
- GET /health
- POST /notes
- GET /notes?page=1&page_size=10&q=search
- GET /notes/{id}
- PUT /notes/{id}
- DELETE /notes/{id}
- POST /utils/seed?count=5
- POST /utils/reset

Schema:
- Note: { id, title, content, tags, created_at, updated_at }

CORS:
- Enabled for localhost origins.
