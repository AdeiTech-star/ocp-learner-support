import logging
from app.nudges import create_draft, send_approved_draft, reject_draft

logging.basicConfig(level=logging.INFO)

# Happy path: create → approve → send
draft_id = create_draft(
    to_email="nthema@andrew.cmu.edu",
    subject="Lifecycle test — approved",
    html_body="<p>This one gets sent.</p>",
    user_id=1,
    nudge_type="flag_yellow",
    template_id="tmpl_yellow_v1",
)
print(f"Created draft: {draft_id}")
send_approved_draft(draft_id, reviewer_id="nthabiseng@test")

# Reject path: create → reject
draft_id_2 = create_draft(
    to_email="nthema@andrew.cmu.edu",
    subject="Lifecycle test — rejected",
    html_body="<p>This one gets rejected.</p>",
    user_id=1,
    nudge_type="flag_yellow",
    template_id="tmpl_yellow_v1",
)
print(f"Created draft: {draft_id_2}")
reject_draft(draft_id_2, reviewer_id="nthabiseng@test", notes="Tone too formal")

print("Done. Check the DB.")