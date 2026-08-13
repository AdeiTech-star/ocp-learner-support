import logging
from app.email_student import send_email

logging.basicConfig(level=logging.INFO)

result = send_email(
    to="nthema@andrew.cmu.edu",  
    subject="Wrapper smoke test",
    html="<p>Sent via app.email_client.send_email</p>",
)
print(result)