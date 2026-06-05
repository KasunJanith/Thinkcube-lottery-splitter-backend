# Backend Startup Instructions

## Quick Start

1. Open Command Prompt in the backend directory:
```
cd "d:\My Github Projects\Cubematrix\Thinkcube-lottery-splitter-backend"
```

2. Start the server with one of these commands:

**Option A - Using the batch file (easiest):**
```
start_server.bat
```

**Option B - Using Python directly:**
```
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Option C - Using the startup script:**
```
python start_backend.py
```

## What was fixed

✓ Added SQLAlchemy to requirements.txt
✓ Updated main.py with proper CORS middleware configuration
✓ Simplified CORS settings to allow all origins (for development)
✓ Added health check endpoint at /health
✓ Added error handling in the by-date endpoint
✓ Created startup scripts for easy server management

## Verifying the Fix

After starting the server, you should see:
- "Application startup complete" message
- Server running at http://0.0.0.0:8000

Then test in your browser or frontend:
- http://localhost:8000/ - should return {"status": "ok"}
- http://localhost:8000/health - should return {"status": "healthy"}
- http://localhost:8000/api/v1/sessions/by-date?date=2026-06-03 - should work now!

## If you still get CORS errors

1. Make sure the server is fully restarted (not cached)
2. Hard refresh your frontend (Ctrl+Shift+R in browser)
3. Check the server console for any error messages
4. Verify the server is responding: http://localhost:8000/health
