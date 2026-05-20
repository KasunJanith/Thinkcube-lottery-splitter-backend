from fastapi import FastAPI
from app.routers import upload

app = FastAPI(
    title="DBF Splitter & Excel Exporter",
    description="Backend for uploading DBF archives and processing lottery files",
    version="0.1.0"
)

# Include routers
app.include_router(upload.router, prefix="/api/v1", tags=["upload"])

# Root endpoint (health check)
@app.get("/")
async def root():
    return {"message": "DBF Extractor API is running"}