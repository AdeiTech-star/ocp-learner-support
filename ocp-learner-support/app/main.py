from fastapi import FastAPI
from pydantic import BaseModel

from app.config import settings
from app.integrations.agent import personalize
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pathlib import Path



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