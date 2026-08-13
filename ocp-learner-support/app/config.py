from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
    database_url: str

    # Email
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = ""

    # Canvas
    canvas_api_url: str = ""
    canvas_api_token: str = ""

    resend_api_key: str = ""
    resend_from_email: str = ""


settings = Settings()