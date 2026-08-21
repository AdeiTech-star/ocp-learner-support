from fastapi import FastAPI
from pydantic import BaseModel

from app.config import settings
from app.integrations.agent import personalize
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pathlib import Path
from fastapi import HTTPException, BackgroundTasks
import os

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

app = FastAPI(title="CMU Certificates Learner Support")

# Jinja templates. I will need to edit this once we have a flag so we know what to send when(flag)
TEMPLATE_DIR = Path(__file__).parent / "templates" / "preview"
jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    undefined=StrictUndefined,
    autoescape=False,
)

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

#late submission message

class LateSubmissionRequest(BaseModel):
    context: dict
    
@app.post("/personalize/late-submission")
def personalize_late_submission(req: LateSubmissionRequest):
    template = jinja_env.get_template("late_sub_a.j2")
    rendered = template.render(**req.context)
    draft = personalize(rendered, req.context)
    return {
        "rendered_template": rendered,
        "personalized_draft": draft,
    }

@app.post("/admin/run-pipeline")
def trigger_pipeline(secret: str, background_tasks: BackgroundTasks):
    """
    Manually trigger the ingestion pipeline.
    Requires ?secret=<ADMIN_SECRET> query param.
    Runs in the background so the request returns immediately.
    """
    if secret != os.getenv("ADMIN_SECRET"):
        raise HTTPException(status_code=403, detail="Forbidden")
    # Import inside function to avoid circular imports at startup
    from app.ingestion.pipeline import run_pipeline
    background_tasks.add_task(run_pipeline)
    return {"status": "started", "message": "Pipeline running in background. Check logs for progress."}