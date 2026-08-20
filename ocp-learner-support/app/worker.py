"""Background worker.

Reads jobs from Postgres, runs personalization, writes to audit log.
For now this is a stub that just proves the container starts and can read config.
Week 2 will add: arq queue integration, audit log writes, SendGrid dispatch.
"""
import time

from app.config import settings


def main():
    print(f"Worker started.")
    print(f"  LLM provider: {settings.llm_provider}")
    print(f"  Database: {settings.database_url}")
    print(f"  LangSmith tracing: {settings.langsmith_tracing}")

    while True:
        # Week 2: poll Postgres jobs table, dispatch to app.integrations.agent.personalize()
        print("Worker heartbeat...")
        time.sleep(10)


if __name__ == "__main__":
    main()