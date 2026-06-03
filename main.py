from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import upload, split

app = FastAPI(title="DBF Splitter & Excel Exporter", version="0.3.0")

# Allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite default
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router, prefix="/api/v1", tags=["upload"])
app.include_router(split.router, prefix="/api/v1", tags=["split"])

@app.get("/")
async def root():
    return {"message": "DBF Extractor API is running"}