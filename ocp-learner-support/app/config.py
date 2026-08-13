from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv
load_dotenv()

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    # LLM providers
    groq_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    llm_provider: str = "groq"

    # Observability
    langsmith_api_key: str = ""
    langsmith_tracing: bool = True
    langsmith_project: str = "ocp-learner-support"

    # Storage
    database_url: str=""

    # Email
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = ""

    # Canvas
    canvas_api_url: str = ""
    canvas_api_token: str = ""

    #email senders
    resend_api_key: str = ""
    resend_from_email: str = ""

    langsmith_project_url: str = "https://smith.langchain.com/o/6c64b576-0ee6-4d32-bf8e-a0113fe2c2fa/projects/p/5e6f45cc-a84d-41ef-a93d-55a0b8224fdf?timeModel=%7B%22duration%22%3A%221d%22%7D"


settings = Settings()