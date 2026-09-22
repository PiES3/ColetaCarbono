import os

from dotenv import load_dotenv
from src.app import app

load_dotenv()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=os.getenv("SERVER_IP_ADDR", "127.0.0.1"), port=8000, reload=True)