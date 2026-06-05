@echo off
REM Start the FastAPI backend server
cd /d "d:\My Github Projects\Cubematrix\Thinkcube-lottery-splitter-backend"
echo.
echo =========================================
echo  Starting FastAPI Backend Server
echo =========================================
echo.
echo Server will be available at: http://localhost:8000
echo.
echo Press Ctrl+C to stop the server
echo.
"C:\Users\EWIS\AppData\Local\Programs\Python\Python311\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
pause
