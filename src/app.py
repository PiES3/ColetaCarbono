from fastapi import FastAPI

app = FastAPI(
    title="ColetaCarbono",
    version="0.1.0",
    redirect_slashes=False,
)