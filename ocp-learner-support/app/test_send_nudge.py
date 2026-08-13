import logging
from app.nudges import send_nudge

logging.basicConfig(level=logging.INFO)

nudge_id = send_nudge(
    to="nthema@andrew.cmu.edu",
    subject="send_nudge smoke test",
    html="<p>Sent + logged via app.nudges.send_nudge</p>",
    user_id=1,
    nudge_type="flag_yellow",
    template_id="tmpl_yellow_v1_test",
)
print(f"Inserted nudge_id={nudge_id}")