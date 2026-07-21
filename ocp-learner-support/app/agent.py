from langchain_groq import ChatGroq
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from app.config import settings


def get_llm():
    """Return the configured chat model. Provider is swappable via env."""
    if settings.llm_provider == "groq":
        return ChatGroq(model="llama-3.3-70b-versatile", temperature=0.3)
    if settings.llm_provider == "anthropic":
        return ChatAnthropic(model="claude-sonnet-4-5", temperature=0.3)
    if settings.llm_provider == "openai":
        return ChatOpenAI(model="gpt-4o-mini", temperature=0.3)
    raise ValueError(f"Unknown provider: {settings.llm_provider}")


PERSONALIZE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You rewrite templated learner support messages to sound warm and "
     "personal. Keep under 500 words. This should be a do-not-reply email.Do not add new facts. Do not change "
     "deadlines, course names, or scores. Return only the rewritten message, "
     "no preamble."),
    ("user", "Learner context:\n{context}\n\nTemplate:\n{template}"),
])


def personalize(template: str, context: dict) -> str:
    """Rewrite a templated message using the LLM. Single trust boundary."""
    llm = get_llm()
    chain = PERSONALIZE_PROMPT | llm
    result = chain.invoke({"template": template, "context": str(context)})
    return result.content