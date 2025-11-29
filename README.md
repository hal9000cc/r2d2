# R2D2

Project with Vue.js frontend and FastAPI backend.

## Project Structure

```
r2d2/
├── frontend/          # Vue.js application
├── backend/           # FastAPI application
└── README.md
```

## Installation and Running

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate  # Windows

pip install -r requirements.txt
cp .env.example .env
# Edit .env file

uvicorn app.main:app --reload
```

Backend will be available at: http://localhost:8202

### Frontend

```bash
cd frontend
npm install
cp .env.example .env
# Edit .env file if needed

npm run dev
```

Frontend will be available at: http://localhost:3000

## Development

- Backend API documentation: http://localhost:8202/docs
- Backend alternative documentation: http://localhost:8202/redoc

