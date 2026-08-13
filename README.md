# AIML04 Learner Support System

An AI-powered system that monitors student engagement in the AI for Africa Certificate Program (AIML04: Math Foundations), identifies learners at risk of falling behind, and enables the course team to send timely, personalised support messages.

## What it does

Every time the pipeline runs, it pulls data from Canvas LMS, stores it in a PostgreSQL database, computes a risk profile for each student, raises flags for at-risk students, and updates a live dashboard the course team can use to see who needs help.

## How to run it locally

**Prerequisites:** Docker Desktop installed and running, Python 3.11+, a Canvas API token for AIML04.

```bash
git clone https://github.com/AdeiTech-star/ocp-learner-support.git
cd ocp-learner-support

# Create your environment file
cp .env.example .env
# Edit .env and fill in: DATABASE_URL, canvas_api_url, canvas_api_token

# Start the database
docker compose up db -d

# Install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run the pipeline (pulls Canvas data, computes flags)
python3 -m app.pipeline

# Start the dashboard
bash run_dashboard.sh
# Open http://localhost:8501 in your browser
```

## File structure
```
app/
  canvas.py         Canvas API client. Handles authentication, pagination, retries.
                     Contains DEADLINE_MAP mapping assignment IDs to roadmap deadlines.
  ingestion.py       All sync functions: students, assignments, submissions, enrollments,
                     quizzes, student summaries, course activity.
  analytics.py       Reads ingested data, computes per-student risk signals, writes to
                     student_risk_signals table.
  flags.py           Detection engine. Reads student_risk_signals, applies 8 rules,
                     writes to flag_events. Deduplicates on re-run.
  pipeline.py        Main orchestrator. Calls all sync functions then analytics then flags.
  dashboard.py       Four-page Streamlit dashboard: Cohort Overview, Student Drill-Down,
                     Flag Log, Approval Queue (placeholder).
  config.py          Settings loaded from .env file.
schema.sql           Full PostgreSQL schema: 13 tables, 12 indexes.
run_dashboard.sh      One-command dashboard launcher (handles PYTHONPATH).
```

## Database tables

| Table | Rows | Purpose |
|---|---|---|
| courses | 1 | AIML04 course metadata |
| users | 10 | Student Canvas IDs and emails. No names stored. |
| enrollments | 10 | Last login, hours in Canvas, current and final score |
| assignments | 19 | All assignments with roadmap deadlines hardcoded by assignment ID |
| submissions | 170 | Every student-assignment pair. Key column: days_from_deadline |
| quizzes | 48 | All quizzes in the course |
| quiz_submissions | 158 | All quiz attempts with scores and timing |
| student_summaries | 10 | Page views, participations, tardiness breakdown from Canvas analytics |
| gate_calendar | 5 | Hard-concept weeks: SVD, M1 Lab, Backpropagation, Bayes, Entropy/KL |
| student_risk_signals | 10 | Computed risk profile per student (updated every pipeline run) |
| flag_events | ~12 | Active flags from the detection engine |
| course_activity | varies | Daily page views and participation counts for the cohort |
| email_log | 0 | Populated when emails are sent (Week 5) |

## Flag rules

| Rule | Type | Condition |
|---|---|---|
| R1 | Red | Zero submissions AND silent > 14 days |
| R2 | Red | Average timing < -10 days AND < 3 submissions |
| R3 | Red | Gate approaching within 7 days AND average timing < -5 days |
| Y1 | Yellow | Zero submissions AND silent 7-14 days |
| Y1b | Yellow | Zero formal submissions AND logged in within 7 days |
| Y2 | Yellow | Average timing -5 to -10 days AND >= 3 submissions |
| Y3 | Yellow | Timing trend = Worsening AND average timing < 0 |
| Y4 | Yellow | Has submissions AND final score < 70% |

## Key design decisions

**No names in the database.** Only Canvas IDs and emails are stored. Names are never written to any table.

**Roadmap deadlines hardcoded.** Canvas returns null for all due dates in AIML04. Deadlines are matched to assignment IDs from the roadmap document. If the roadmap changes, update DEADLINE_MAP in app/canvas.py.

**Human approval required.** Nothing is sent to a student without a human reviewing and approving it. The Approval Queue page in the dashboard is where this happens.

**Gates are not a Canvas concept.** The gate_calendar table was created manually from the roadmap. Canvas knows nothing about gates.

## Running for a new cohort

1. Update COURSE_ID in app/canvas.py
2. Update DEADLINE_MAP in app/canvas.py with the new course's assignment IDs and deadlines
3. Update gate_calendar entries in app/ingestion.py load_gate_calendar()
4. Clear the database: docker compose down -v && docker compose up db -d
5. Run the schema: docker exec -i <db-container> psql -U ocp -d ocp < schema.sql
6. Run the pipeline: python3 -m app.pipeline

## Who owns what

Gentille Uwera (Intern A — Data and Dashboard): canvas.py, ingestion.py, analytics.py, flags.py, pipeline.py, dashboard.py, schema.sql

Nthabiseng Thema (Intern B — AI and Trust): agent.py, audit.py, fairness.py, review.py, app/templates/

Shared (coordinate before editing): main.py, config.py, worker.py, docker-compose.yml, Dockerfile, requirements.txt
