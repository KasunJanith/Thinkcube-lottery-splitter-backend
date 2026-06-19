from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base
from app.seed import init_db
from app.routers import upload, orders, assignments, split, results
import logging
from app.routers import dashboard

logging.basicConfig(level=logging.DEBUG)

Base.metadata.create_all(bind=engine)
init_db()

app = FastAPI()

# Add CORS middleware - MUST be first/outermost
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(upload.router, prefix="/api/v1", tags=["upload"])
app.include_router(orders.router, prefix="/api/v1", tags=["orders"])
app.include_router(assignments.router, prefix="/api/v1", tags=["assignments"])
app.include_router(split.router, prefix="/api/v1", tags=["split"])
app.include_router(dashboard.router, prefix="/api/v1", tags=["dashboard"])
app.include_router(results.router, prefix="/api/v1", tags=["results"])
@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/health")
def health():
    """Health check endpoint"""
    return {"status": "healthy"}
