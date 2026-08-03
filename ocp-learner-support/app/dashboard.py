"""
Learner support dashboard for AIML04.
Three pages: Cohort Overview, Student Drill-Down, Flag Log.
Owned by: Gentille Uwera
"""
import psycopg
import pandas as pd
import plotly.express as px
import streamlit as st
from app.config import settings

st.set_page_config(
    page_title="AIML04 Learner Support",
    page_icon="🎓",
    layout="wide"
)


@st.cache_resource
def get_conn():
    return psycopg.connect(settings.database_url)


def get_df(query: str, params=None) -> pd.DataFrame:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(query, params or ())
        rows = cur.fetchall()
        cols = [d.name for d in cur.description]
    return pd.DataFrame(rows, columns=cols)


def status_color(flag_type):
    if flag_type == "red":
        return "🔴 "
    elif flag_type == "yellow":
        return "🟡 "
    return "🟢 "


# ── SIDEBAR ───────────────────────────────────────────────────────────────
st.sidebar.title("AIML04 Learner Support")
st.sidebar.markdown("Course: Math Foundations")
page = st.sidebar.radio(
    "Navigate",
    ["Cohort Overview", "Student Drill-Down", "Flag Log"]
)

# Show last pipeline run time
run_df = get_df(
    "SELECT started_at, status FROM sync_runs ORDER BY run_id DESC LIMIT 1"
)
if not run_df.empty:
    last_run = run_df.iloc[0]["started_at"]
    status = run_df.iloc[0]["status"]
    st.sidebar.markdown(f"**Last sync:** {str(last_run)[:16]} UTC")
    st.sidebar.markdown(f"**Status:** {status}")

# ── PAGE 1: COHORT OVERVIEW ───────────────────────────────────────────────
if page == "Cohort Overview":
    st.title("Cohort Overview")
    st.markdown("AIML04: Math Foundations · 10 enrolled students")

    # Pull combined data
    cohort_df = get_df("""
        SELECT
            u.user_id,
            u.email,
            r.total_submissions,
            r.avg_days_from_deadline,
            r.timing_trend,
            r.days_since_last_login,
            r.engagement_ratio,
            r.gate_approaching,
            r.gate_name,
            r.days_until_gate,
            e.current_score,
            e.last_activity_at,
            ROUND(e.total_activity_time / 3600.0, 1) AS hrs_in_canvas
        FROM users u
        LEFT JOIN student_risk_signals r ON u.user_id = r.user_id
        LEFT JOIN enrollments e ON u.user_id = e.user_id
        ORDER BY u.user_id
    """)

    # Pull worst flag per student
    flags_df = get_df("""
        SELECT DISTINCT ON (user_id)
            user_id,
            flag_type,
            reason
        FROM flag_events
        WHERE resolved = 0
        ORDER BY user_id,
            CASE flag_type WHEN 'red' THEN 0 WHEN 'yellow' THEN 1 ELSE 2 END
    """)
    flag_map = {
        row["user_id"]: (row["flag_type"], row["reason"])
        for _, row in flags_df.iterrows()
    }

    # Summary counts
    red_count    = sum(1 for v in flag_map.values() if v[0] == "red")
    yellow_count = sum(1 for v in flag_map.values() if v[0] == "yellow")
    green_count  = len(cohort_df) - red_count - yellow_count

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Students", len(cohort_df))
    col2.metric("🔴 Red", red_count)
    col3.metric("🟡 Yellow", yellow_count)
    col4.metric("🟢 Green", green_count)

    st.markdown("---")

    # Build display table
    rows = []
    for _, row in cohort_df.iterrows():
        uid = row["user_id"]
        flag_type, flag_reason = flag_map.get(uid, ("green", "No issues detected"))
        icon = status_color(flag_type)
        avg_t = row["avg_days_from_deadline"]
        timing_str = f"{avg_t:+.1f}d" if pd.notna(avg_t) else "no data"
        silent = row["days_since_last_login"]
        if silent is None:
            silent_str = "never"
        elif silent == 0:
            silent_str = "today"
        else:
            silent_str = f"{int(silent)}d ago"
        gate_str = ""
        if row["gate_approaching"]:
            d = int(row["days_until_gate"]) if row["days_until_gate"] is not None else 0
            gate_str = f"⚠️ {row['gate_name']} {'TODAY' if d == 0 else f'in {d}d'}"
        rows.append({
            "Status":      icon,
            "Student ID":  uid,
            "Submitted":   int(row["total_submissions"]) if row["total_submissions"] is not None else 0,
            "Avg Timing":  timing_str,
            "Trend":       row["timing_trend"] or "no data",
            "Last Login":  silent_str,
            "Engagement":  f"{row['engagement_ratio']*100:.0f}%" if row["engagement_ratio"] is not None else "0%",
            "Score":       f"{row['current_score']:.0f}%" if pd.notna(row["current_score"]) else "N/A",
            "Hrs Canvas":  row["hrs_in_canvas"] or 0,
            "Gate Alert":  gate_str,
            "Flag Reason": flag_reason,
        })

    display_df = pd.DataFrame(rows)
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # Engagement chart
    st.subheader("Page Views vs Submissions")
    chart_df = get_df("""
        SELECT u.user_id, ss.page_views, r.total_submissions
        FROM users u
        LEFT JOIN student_summaries ss ON u.user_id = ss.user_id
        LEFT JOIN student_risk_signals r ON u.user_id = r.user_id
    """)
    if not chart_df.empty:
        chart_df["page_views"] = chart_df["page_views"].fillna(0)
        chart_df["total_submissions"] = chart_df["total_submissions"].fillna(0)
        chart_df["user_id"] = chart_df["user_id"].astype(str)
        fig = px.scatter(
            chart_df,
            x="page_views",
            y="total_submissions",
            text="user_id",
            labels={"page_views": "Page Views", "total_submissions": "Assignments Submitted"},
            title="Engagement vs Submission Activity"
        )
        fig.update_traces(textposition="top center", marker_size=12)
        st.plotly_chart(fig, use_container_width=True)

# ── PAGE 2: STUDENT DRILL-DOWN ────────────────────────────────────────────
elif page == "Student Drill-Down":
    st.title("Student Drill-Down")

    users_df = get_df("SELECT user_id, email FROM users ORDER BY user_id")
    options = [f"{row['user_id']} ({row['email']})" for _, row in users_df.iterrows()]
    selected = st.selectbox("Select a student", options)
    uid = int(selected.split(" ")[0])

    col1, col2 = st.columns(2)

    # Enrollment summary
    enrol_df = get_df("""
        SELECT enrollment_state, last_activity_at,
               ROUND(total_activity_time/3600.0,1) as hrs,
               current_score, final_score
        FROM enrollments WHERE user_id = %s
    """, (uid,))
    if not enrol_df.empty:
        e = enrol_df.iloc[0]
        col1.metric("Enrollment State", e["enrollment_state"])
        col1.metric("Hours in Canvas", e["hrs"] or 0)
        col1.metric("Current Score", f"{e['current_score']:.1f}%" if e["current_score"] else "N/A")
        col2.metric("Last Login", str(e["last_activity_at"])[:10] if e["last_activity_at"] else "Never")
        col2.metric("Final Score", f"{e['final_score']:.2f}%" if e["final_score"] else "N/A")

    st.markdown("---")

    # Risk signals
    st.subheader("Risk Signals")
    risk_df = get_df("""
        SELECT avg_days_from_deadline, timing_trend, days_since_last_login,
               total_submissions, zero_submissions, engagement_ratio,
               gate_approaching, gate_name, days_until_gate, computed_at
        FROM student_risk_signals WHERE user_id = %s
    """, (uid,))
    if not risk_df.empty:
        risk_df = risk_df.rename(columns={
            "avg_days_from_deadline": "Avg Days from Deadline",
            "timing_trend": "Trend",
            "days_since_last_login": "Days Since Login",
            "total_submissions": "Submitted",
            "zero_submissions": "Zero Submissions",
            "engagement_ratio": "Engagement Ratio",
            "gate_approaching": "Gate Approaching",
            "gate_name": "Gate Name",
            "days_until_gate": "Days Until Gate",
            "computed_at": "Computed At"
        })
        st.dataframe(risk_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # Submission timeline
    st.subheader("Submission Timeline")
    subs_df = get_df("""
        SELECT a.name, s.submitted_at, s.days_from_deadline,
               s.score, s.workflow_state, s.late
        FROM submissions s
        JOIN assignments a ON s.assignment_id = a.assignment_id
        WHERE s.user_id = %s
        ORDER BY a.due_at_roadmap
    """, (uid,))
    if not subs_df.empty:
        submitted = subs_df[subs_df["submitted_at"].notna()].copy()
        if not submitted.empty:
            submitted["submitted_at"] = submitted["submitted_at"].astype(str).str[:10]
            submitted["days_from_deadline"] = submitted["days_from_deadline"].round(2)
            st.dataframe(submitted[["name", "submitted_at", "days_from_deadline", "score", "workflow_state"]],
                        use_container_width=True, hide_index=True)

            fig2 = px.bar(
                submitted,
                x="name",
                y="days_from_deadline",
                color=submitted["days_from_deadline"].apply(lambda x: "Early" if x >= 0 else "Late"),
                color_discrete_map={"Early": "#2ecc71", "Late": "#e74c3c"},
                labels={"name": "Assignment", "days_from_deadline": "Days from Deadline"},
                title=f"Submission Timing for Student {uid}"
            )
            fig2.update_layout(xaxis_tickangle=-45, showlegend=True)
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("No submissions recorded for this student yet.")

    st.markdown("---")

    # Active flags
    st.subheader("Active Flags")
    student_flags = get_df("""
        SELECT flag_type, reason, flagged_at, resolved
        FROM flag_events
        WHERE user_id = %s
        ORDER BY flagged_at DESC
    """, (uid,))
    if not student_flags.empty:
        for _, flag in student_flags.iterrows():
            icon = "🔴 " if flag["flag_type"] == "red" else "🟡 "
            st.markdown(f"{icon} **{flag['flag_type'].upper()}** — {flag['reason']}")
    else:
        st.success("No active flags for this student.")

    st.markdown("---")

    # Quiz history
    st.subheader("Quiz Attempt History")
    quiz_df = get_df("""
        SELECT q.title, qs.score, qs.kept_score, qs.attempt,
               qs.workflow_state,
               LEFT(qs.started_at::text, 10) as date
        FROM quiz_submissions qs
        JOIN quizzes q ON qs.quiz_id = q.quiz_id
        WHERE qs.user_id = %s
        ORDER BY qs.started_at
    """, (uid,))
    if not quiz_df.empty:
        st.dataframe(quiz_df, use_container_width=True, hide_index=True)
    else:
        st.info("No quiz attempts recorded.")

# ── PAGE 3: FLAG LOG ──────────────────────────────────────────────────────
elif page == "Flag Log":
    st.title("Flag Log")
    st.markdown("All flags raised by the detection engine, most recent first.")

    all_flags = get_df("""
        SELECT f.flag_id, f.user_id, u.email, f.flag_type,
               f.reason, f.flagged_at, f.resolved
        FROM flag_events f
        JOIN users u ON f.user_id = u.user_id
        ORDER BY f.flagged_at DESC
    """)

    if all_flags.empty:
        st.info("No flags raised yet.")
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Flags", len(all_flags))
        col2.metric("🔴 Red", len(all_flags[all_flags["flag_type"] == "red"]))
        col3.metric("🟡 Yellow", len(all_flags[all_flags["flag_type"] == "yellow"]))

        st.markdown("---")

        # Color-coded display
        for _, row in all_flags.iterrows():
            icon = "🔴 " if row["flag_type"] == "red" else "🟡 "
            resolved = "✅ Resolved" if row["resolved"] else "⏳ Open"
            st.markdown(
                f"{icon} **User {row['user_id']}** ({row['email']}) — "
                f"{row['reason']}  \n"
                f"*Flagged: {str(row['flagged_at'])[:16]} UTC · {resolved}*"
            )
            st.markdown("---")
