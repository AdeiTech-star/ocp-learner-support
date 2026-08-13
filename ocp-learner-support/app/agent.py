from langchain_groq import ChatGroq
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langsmith import traceable, get_current_run_tree

from app.config import settings

import os
os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
os.environ["LANGSMITH_TRACING"] = str(settings.langsmith_tracing).lower()
os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project


def get_llm():
    """Return the configured chat model. Provider is swappable via env."""
    if settings.llm_provider == "groq":
        return ChatGroq(model="llama-3.3-70b-versatile", temperature=0.3, groq_api_key=settings.groq_api_key)
    if settings.llm_provider == "anthropic":
        return ChatAnthropic(model="claude-sonnet-4-5", temperature=0.3)
    if settings.llm_provider == "openai":
        return ChatOpenAI(model="gpt-4o-mini", temperature=0.3)
    raise ValueError(f"Unknown provider: {settings.llm_provider}")


PERSONALIZE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You rewrite templated learner support messages to sound warm and "
     "personal. Keep under 500 words. This should be a do-not-reply email. "
     "Do not add new facts. Do not change deadlines, course names, or scores. "
     "Return only the rewritten message, no preamble."),
    ("user", "Learner context:\n{context}\n\nTemplate:\n{template}"),
])


@traceable(
    name="personalize_nudge",
    run_type="chain",
    metadata={"component": "personalization"},
)
def personalize(
    template: str,
    context: dict,
    *,
    flag_code: str | None = None,
    template_name: str | None = None,
    nudge_type: str | None = None,
    user_id: int | None = None,
    severity: str | None = None,
) -> tuple[str, str | None]:
    """Rewrite a templated message using the LLM.

    Returns (rewritten_text, langsmith_run_id). run_id is None if
    tracing is disabled.
    """
    run_tree = get_current_run_tree()
    run_id: str | None = None
    if run_tree is not None:
        run_tree.add_metadata({
            "flag_code": flag_code,
            "template_name": template_name,
            "nudge_type": nudge_type,
            "user_id": user_id,
            "severity": severity,
        })
        run_id = str(run_tree.id)

    llm = get_llm()
    chain = PERSONALIZE_PROMPT | llm
    result = chain.invoke({"template": template, "context": str(context)})
    return result.content, run_id