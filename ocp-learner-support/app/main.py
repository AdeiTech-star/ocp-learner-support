from fastapi import FastAPI
from pydantic import BaseModel

from app.config import settings
from app.agent import personalize

app = FastAPI(title="OCP Learner Support")


class PersonalizeRequest(BaseModel):
    template: str
    context: dict


@app.get("/health")
def health():
    """Cheap check that the service is up and configured."""
    return {
        "status": "ok",
        "llm_provider": settings.llm_provider,
        "langsmith_tracing": settings.langsmith_tracing,
    }


@app.post("/personalize/preview")
def preview_personalization(req: PersonalizeRequest):
    """Dev endpoint. Personalize without touching the queue or audit log."""
    draft = personalize(req.template, req.context)
    return {"draft": draft}