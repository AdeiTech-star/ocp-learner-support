import resend
from app.config import settings

resend.api_key = settings.resend_api_key

params: resend.Emails.SendParams = {
    "from": settings.resend_from_email,
    "to": ["nthema@andrew.cmu.edu"],  # replace with the email you signed up with
    "subject": "OCP Resend smoke test",
    "html": "<p>If you can read this, the key works.</p>",
}

email = resend.Emails.send(params)
print(email)