from fastapi import FastAPI

app = FastAPI(
    title="API do StudyRats",
    version="0.1.0",
    redirect_slashes=False,
)