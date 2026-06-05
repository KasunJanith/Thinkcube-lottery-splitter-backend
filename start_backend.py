#!/usr/bin/env python
"""Minimal test to start the FastAPI app"""
import sys
import os

# Change to the correct directory
os.chdir(r'd:\My Github Projects\Cubematrix\Thinkcube-lottery-splitter-backend')

try:
    print("=" * 60)
    print("FASTAPI BACKEND STARTUP TEST")
    print("=" * 60)
    
    print("\n[1/5] Importing FastAPI...")
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    print("✓ FastAPI imported")
    
    print("\n[2/5] Importing database and seed...")
    from app.database import engine, Base
    from app.seed import init_db
    print("✓ Database modules imported")
    
    print("\n[3/5] Initializing database...")
    Base.metadata.create_all(bind=engine)
    print("✓ Tables created")
    init_db()
    print("✓ Database seeded")
    
    print("\n[4/5] Importing routers...")
    from app.routers import upload, orders, assignments, split
    print("✓ All routers imported")
    
    print("\n[5/5] Creating FastAPI app with CORS...")
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(upload.router, prefix="/api/v1", tags=["upload"])
    app.include_router(orders.router, prefix="/api/v1", tags=["orders"])
    app.include_router(assignments.router, prefix="/api/v1", tags=["assignments"])
    app.include_router(split.router, prefix="/api/v1", tags=["split"])
    
    @app.get("/")
    def root():
        return {"status": "ok"}
    
    @app.get("/health")
    def health():
        return {"status": "healthy"}
    
    print("✓ App created with all routers")
    
    print("\n" + "=" * 60)
    print("✓ ALL STARTUP CHECKS PASSED!")
    print("=" * 60)
    print("\nStarting server on http://0.0.0.0:8000")
    print("Press Ctrl+C to stop the server")
    print("-" * 60)
    
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
    
except Exception as e:
    print(f"\n✗ ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
