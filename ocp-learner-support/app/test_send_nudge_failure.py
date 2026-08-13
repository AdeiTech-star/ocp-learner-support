import logging
from app.email_student import EmailSendError
from app.nudges import send_nudge

logging.basicConfig(level=logging.INFO)

try:
    nudge_id = send_nudge(
        to="not-a-real-email-address",  # malformed, Resend will reject
        subject="failure path test",
        html="<p>should never arrive</p>",
        user_id=1,
        nudge_type="flag_yellow",
        template_id="tmpl_yellow_v1_test",
    )
    print(f"UNEXPECTED SUCCESS: nudge_id={nudge_id}")
except EmailSendError as e:
    print(f"Got expected EmailSendError: {e}")