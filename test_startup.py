#!/usr/bin/env python
"""Test script to verify the backend starts without errors"""
import sys
import traceback

try:
    print("Testing imports...")
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    print("✓ FastAPI imports OK")
    
    from app.database import engine, Base
    print("✓ Database imports OK")
    
    from app.seed import init_db
    print("✓ Seed imports OK")
    
    from app.routers import upload, orders, assignments, split
    print("✓ Router imports OK")
    
    print("\nTesting database creation...")
    Base.metadata.create_all(bind=engine)
    print("✓ Database tables created")
    
    print("Testing seed initialization...")
    init_db()
    print("✓ Database seeded")
    
    print("\nTesting FastAPI app creation...")
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
    print("✓ CORS middleware added")
    
    app.include_router(upload.router, prefix="/api/v1", tags=["upload"])
    app.include_router(orders.router, prefix="/api/v1", tags=["orders"])
    app.include_router(assignments.router, prefix="/api/v1", tags=["assignments"])
    app.include_router(split.router, prefix="/api/v1", tags=["split"])
    print("✓ All routers included")
    
    print("\n✓ All startup checks passed! Backend is ready to run.")
    print("\nTo start the server, run:")
    print("  uvicorn main:app --host 0.0.0.0 --port 8000 --reload")
    
except Exception as e:
    print(f"\n✗ Error during startup: {e}")
    traceback.print_exc()
    sys.exit(1)
