import uvicorn
import os

os.chdir(r'd:\My Github Projects\Cubematrix\Thinkcube-lottery-splitter-backend')

if __name__ == "__main__":
    print("Starting server on http://0.0.0.0:8000")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
