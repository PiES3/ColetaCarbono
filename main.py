from src.app import app
from src.core.config import SERVER_IP_ADDR, SERVER_PORT, SERVER_RELOAD

__all__ = ["app"]

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=SERVER_IP_ADDR,
        port=SERVER_PORT,
        reload=SERVER_RELOAD,
    )
