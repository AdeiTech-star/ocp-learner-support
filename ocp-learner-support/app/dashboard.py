"""
Learner support dashboard for AIML04.
Four pages: Cohort Overview, Student Drill-Down, Flag Log, Approval Queue.
Owned by: Gentille Uwera
"""
import psycopg
import pandas as pd
import plotly.express as px
import streamlit as st
from app.config import settings
import pandas as pd

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
    ["Cohort Overview", "Student Drill-Down", "Flag Log", "Approval Queue"]
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
            e.final_score,
            e.last_activity_at,
            ROUND(e.total_activity_time / 3600.0, 1) AS hrs_in_canvas,
            ss.page_views
        FROM users u
        LEFT JOIN student_risk_signals r ON u.user_id = r.user_id
        LEFT JOIN enrollments e ON u.user_id = e.user_id
        LEFT JOIN student_summaries ss ON u.user_id = ss.user_id
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
    col1.metric("Total Students", len(cohort_df),
        help="Total number of enrolled students. Test student excluded.")
    col2.metric("🔴 Red", red_count,
        help="Students with at least one red flag. Red flags require urgent human attention — the student is severely behind, has gone silent, or is approaching a hard concept week while already late.")
    col3.metric("🟡 Yellow", yellow_count,
        help="Students with at least one yellow flag. Yellow flags are warning signals — the student is drifting behind or engaging but not submitting.")
    col4.metric("🟢 Green", green_count,
        help="Students with no active flags or a completed final score of 100%.")

    st.markdown("---")

    # Build display table
    rows = []
    for _, row in cohort_df.iterrows():
        uid = row["user_id"]
        flag_type, flag_reason = flag_map.get(uid, ("green", "No issues detected"))
        if row.get("final_score") == 100.0:
            flag_type, flag_reason = "green", "Course completed"
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
            "Trend": {
                "improving": "Improving",
                "worsening": "Worsening",
                "stable": "Stable",
                "insufficient_data": "Insufficient data",
                "no_data": "No submissions",
                "completed": "Completed ✅",
                None: "No submissions"
            }.get(row["timing_trend"], row["timing_trend"] or "none yet"),
            "Last Login":  silent_str,
"Page Views":  int(row["page_views"]) if pd.notna(row.get("page_views")) else 0,            "Final Score": f"{row['final_score']:.1f}%" if row["final_score"] is not None and row["final_score"] > 0 else "N/A",
            "Hrs Canvas":  row["hrs_in_canvas"] or 0,
            "Gate Alert":  gate_str,
            "Flag Reason": flag_reason,
        })

    display_df = pd.DataFrame(rows)
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Status": st.column_config.TextColumn(
                "Status",
                help="Overall risk level based on the worst active flag. 🔴 Red = urgent action needed. 🟡 Yellow = monitor closely. 🟢 Green = on track. ✅ = course completed."
            ),
            "Student ID": st.column_config.NumberColumn(
                "Student ID",
                help="Canvas student ID. No names are stored in this system for privacy."
            ),
            "Submitted": st.column_config.NumberColumn(
                "Submitted",
                help="Number of assignments submitted out of 19 total. A student with 0 submissions after several weeks is a strong at-risk signal."
            ),
            "Avg Timing": st.column_config.TextColumn(
                "Avg Timing",
                help="Average days relative to the deadline across all submitted assignments. Positive (+) means submitted early. Negative (−) means submitted late. Example: −14.1d means this student submits 14 days after the deadline on average."
            ),
            "Trend": st.column_config.TextColumn(
                "Trend",
                help="Whether submission timing is improving or worsening over time. Compares earliest submissions to most recent ones. A student with a Worsening trend is falling further behind even if their average looks manageable. 'Insufficient data' means fewer than 3 submissions — not enough to determine direction."
            ),
            "Last Login": st.column_config.TextColumn(
                "Last Login",
                help="How long ago the student last did anything in Canvas. Silence is one of the strongest early warning signals. A student silent for more than 14 days with no submissions triggers a red flag."
            ),
            "Page Views": st.column_config.NumberColumn(
                "Page Views",
                help="Total course pages viewed since enrollment. High page views with zero submissions means the student is reading the material but something is blocking them from submitting — a different intervention is needed compared to a student who has not opened the course at all."
            ),
            "Final Score": st.column_config.TextColumn(
                "Final Score",
                help="Overall course score weighted across all 19 assignments including ones not yet submitted. Unsubmitted assignments count as zero. 100% means the course is complete. This is most meaningful at the end of the course when all deadlines have passed."
            ),
            "Gate Alert": st.column_config.TextColumn(
                "Gate Alert",
                help="Warning when a known hard-concept week is approaching within 7 days. Five gates were identified from the course roadmap: SVD, Module 1 Lab, Backpropagation, Bayes Theorem, and Entropy/KL Divergence. Empty when no gate is imminent or all gates have passed."
            ),
            "Flag Reason": st.column_config.TextColumn(
                "Flag Reason",
                help="The reason for the most recent flag raised by the detection engine for this student."
            ),
        }
    )

    st.markdown("---")
    with st.expander("📖 Column guide — click any feature to see how it is calculated"):
        features = [
            ("Status", "The student's overall risk level based on the most severe active flag.",
             "🔴 Red = urgent action needed. 🟡 Yellow = monitor closely. 🟢 Green = on track. ✅ Completed = final score 100%."),
            ("Submitted", "Number of assignments submitted out of 19 total.",
             "Count of rows in submissions table where submitted_at is not null for this student."),
            ("Avg Timing", "Average days relative to the deadline across all submitted assignments.",
             "avg(deadline_date − submitted_at) in days, across all submissions.\n\n+ positive = submitted before deadline (early)\n− negative = submitted after deadline (late)\n\nExample: −14.1d means this student submits 14 days after the deadline on average.\n\nNote: deadlines are from the course roadmap — Canvas does not store due dates for this course."),
            ("Trend", "Whether submission timing is getting better or worse over time.",
             "Steps:\n1. Take all days_from_deadline values in chronological order (earliest submission first)\n2. Split into two equal halves\n3. Compare avg(first half) vs avg(second half)\n\nImproving = second half average is more than 1 day HIGHER (less late or more early)\nWorsening = second half average is more than 1 day LOWER (more late or less early)\nStable = difference is within 1 day either way\nInsufficient data = fewer than 3 submissions\nCompleted = final score is 100% (trend no longer meaningful)\n\nExample: A student whose first 4 submissions averaged −2d and whose last 4 averaged −8d is Worsening — each new submission is coming in later than the last."),
            ("Last Login", "How long ago the student last did anything in Canvas.",
             "today − enrollments.last_activity_at in days.\n\nSilence for 14+ days with zero submissions triggers a Red R1 flag."),
            ("Page Views", "Total course pages opened since enrollment.",
             "Pulled directly from Canvas analytics/student_summaries endpoint.\n\nHigh page views with zero submissions = student is reading but not submitting. A different intervention is needed compared to a student who has not opened the course at all."),
            ("Final Score", "Overall course score weighted across all 19 assignments, including ones not submitted (which count as zero).",
             "Computed by Canvas as: sum(assignment_score × weight) across all 19 assignments.\n\n100% = course completed. 5% = very little submitted.\n\nNote: most meaningful at end of course when all deadlines have passed."),
            ("Hrs Canvas", "Total hours spent in Canvas since enrollment.",
             "enrollments.total_activity_time (in seconds, from Canvas) ÷ 3600."),
            ("Gate Alert", "Warning when a hard-concept week approaches within 7 days.",
             "Five weeks were identified from the AIML04 roadmap where students typically struggle most:\n• SVD — Week 3 (6 Jul)\n• Module 1 Lab — Week 4 (13 Jul)\n• Backpropagation — Week 5 (20 Jul)\n• Bayes Theorem — Week 7 (3 Aug)\n• Entropy / KL Divergence — Week 8 (10 Aug)\n\nAlert fires if gate_date − today ≤ 7 days.\nCurrently empty because all five gates in this cohort have passed."),
            ("Flag Reason", "The reason text from the most recent active flag for this student.",
             "From flag_events.reason, selecting the most recent unresolved flag ordered by severity (red before yellow)."),
        ]

        for name, what, how in features:
            with st.popover(f"**{name}**  —  {what}"):
                st.markdown(how)

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
        st.caption("Each point is one student. Top-right = engaged and submitting. Bottom-right = reading but not submitting. Bottom-left = barely active.")

# ── PAGE 2: STUDENT DRILL-DOWN ────────────────────────────────────────────
elif page == "Student Drill-Down":
    st.title("Student Drill-Down")

    users_df = get_df("SELECT user_id, email FROM users ORDER BY user_id")
    options = [str(row['user_id']) for _, row in users_df.iterrows()]
    selected = st.selectbox("Select a student", options)
    uid = int(selected)

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
        col1.metric("Hours in Canvas", float(e["hrs"]) if e["hrs"] is not None else 0)
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
        st.caption("These signals are computed after each pipeline run and drive the flagging engine. Hover over column headers for descriptions.")
        st.dataframe(risk_df, use_container_width=True, hide_index=True)

        with st.expander("📖 Risk signal guide — click any signal to see how it is calculated"):
            risk_features = [
                ("Avg Days from Deadline", "Average days early or late across all submissions.",
                 "avg(deadline − submitted_at) in days. Positive = early, negative = late."),
                ("Trend", "Whether timing is improving or worsening.",
                 "Compares avg of first-half submissions vs avg of second-half (chronological order).\nImproving = second half is >1d less late. Worsening = second half is >1d more late."),
                ("Days Since Login", "Days since the student last did anything in Canvas.",
                 "today − enrollments.last_activity_at in days."),
                ("Total Submissions", "Number of assignments submitted.", "Count of non-null submitted_at values."),
                ("Zero Submissions", "Whether the student has submitted anything at all.", "1 = zero submissions. 0 = has submitted at least one assignment."),
                ("Engagement Ratio", "This student's page views relative to the most engaged student in the cohort.",
                 "student page_views ÷ max(page_views across all students).\n\nNote: this is a relative measure. It shifts as the top student reads more pages."),
                ("Gate Approaching", "Whether a hard-concept gate falls within the next 7 days.", "1 if any gate_calendar.gate_date is within 7 days of today, else 0."),
                ("Days Until Gate", "Days until the next approaching gate.", "gate_date − today. Only populated when Gate Approaching = 1."),
            ]
            for name, what, how in risk_features:
                with st.popover(f"**{name}**  —  {what}"):
                    st.markdown(how)

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
            st.caption("Green bars = submitted before the deadline. Red bars = submitted after the deadline. Bar height shows how many days early or late.")
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

    col_a, col_b = st.columns(2)
    with col_a:
        type_filter = st.multiselect(
            "Filter by flag type",
            options=["red", "yellow"],
            default=["red", "yellow"],
            format_func=lambda x: "🔴 Red" if x == "red" else "🟡 Yellow"
        )
    with col_b:
        id_filter = st.text_input("Filter by student ID", placeholder="e.g. 27193")

    # Apply filters to all_flags dataframe
    if type_filter:
        all_flags = all_flags[all_flags["flag_type"].isin(type_filter)]
    if id_filter.strip():
        all_flags = all_flags[all_flags["user_id"].astype(str).str.contains(id_filter.strip())]

    st.caption(f"Showing {len(all_flags)} flags")

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
                f"{icon} **User {row['user_id']}** — "
                f"{row['reason']}  \n"
                f"*Flagged: {str(row['flagged_at'])[:16]} UTC · {resolved}*"
            )
            st.markdown("---")

# ── PAGE 4: APPROVAL QUEUE ────────────────────────────────────────────────
elif page == "Approval Queue":
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("Africa/Kigali")

    st.title("Approval Queue")
    st.markdown(
        "Human-in-the-loop review: AI-drafted emails appear here for approval "
        "before anything is sent to a student."
    )

    # Reviewer identity in sidebar — shared across both sub-tabs
    reviewer_email = st.sidebar.text_input(
        "Your email (reviewer ID)",
        value=st.session_state.get("reviewer_email", ""),
        help="Used to record who approved or rejected each draft.",
    )
    st.session_state["reviewer_email"] = reviewer_email

    review_tab, audit_tab = st.tabs(["Review", "Audit log"])

    # ── SUB-TAB: REVIEW ──────────────────────────────────────────────
    with review_tab:
        if not reviewer_email:
            st.warning(
                "Enter your email in the sidebar to approve or reject drafts. "
                "Your identity is written to the audit log.",
                icon="🔒",
            )

        drafts_df = get_df("""
            SELECT
                n.draft_id, n.nudge_id, n.user_id, n.flag_code,
                n.nudge_type, n.subject, n.html_body, n.to_email,
                n.created_at,
                f.reason AS flag_reason, f.flag_type,
                r.days_since_last_login, r.total_submissions,
                r.avg_days_from_deadline
            FROM nudge_events n
            LEFT JOIN LATERAL (
                SELECT reason, flag_type
                FROM flag_events
                WHERE user_id = n.user_id
                  AND resolved = 0
                  AND SPLIT_PART(reason, ':', 1) = n.flag_code
                ORDER BY flagged_at DESC
                LIMIT 1
            ) f ON TRUE
            LEFT JOIN student_risk_signals r ON n.user_id = r.user_id
            WHERE n.delivery_status = 'pending_review'
              AND n.nudge_id = (
                  SELECT MAX(nudge_id) FROM nudge_events n2
                  WHERE n2.draft_id = n.draft_id
              )
            ORDER BY
                CASE f.flag_type WHEN 'red' THEN 0 ELSE 1 END,
                n.created_at DESC
        """)

        red_ct = int((drafts_df["flag_type"] == "red").sum()) if not drafts_df.empty else 0
        yel_ct = int((drafts_df["flag_type"] == "yellow").sum()) if not drafts_df.empty else 0

        c1, c2, c3 = st.columns(3)
        c1.metric("Awaiting Review", len(drafts_df))
        c2.metric("🔴 Red (urgent)", red_ct)
        c3.metric("🟡 Yellow", yel_ct)

        st.markdown("---")

        if drafts_df.empty:
            st.success(
                "No drafts awaiting review. Run the pipeline to generate drafts "
                "from new open flags."
            )
        else:
            st.subheader("Drafts awaiting review")
            st.caption(
                "Red flags appear first. Each draft was generated by the AI agent "
                "from the student's flag and recent activity."
            )

            for _, row in drafts_df.iterrows():
                icon = "🔴" if row["flag_type"] == "red" else "🟡"
                draft_id = str(row["draft_id"])

                with st.container(border=True):
                    col_left, col_right = st.columns([1, 2])

                    with col_left:
                        st.markdown(f"### {icon} Student {row['user_id']}")
                        st.markdown(
                            f"**Flag:** {row['flag_reason'] or row['flag_code']}"
                        )
                        st.markdown(f"**Draft created:** {str(row['created_at'])[:16]} UTC")
                        if pd.notna(row["total_submissions"]):
                            st.markdown(
                                f"**Submitted:** {int(row['total_submissions'])} of 19"
                            )
                        if pd.notna(row["days_since_last_login"]):
                            st.markdown(
                                f"**Last login:** {int(row['days_since_last_login'])} days ago"
                            )
                        st.markdown(f"**To:** `{row['to_email']}`")

                        st.markdown("---")
                        st.markdown("**Actions**")
                        btn_a, btn_b = st.columns(2)
                        approve_clicked = btn_a.button(
                            "✅ Approve & send",
                            key=f"approve_{draft_id}",
                            disabled=not reviewer_email,
                            use_container_width=True,
                        )
                        reject_clicked = btn_b.button(
                            "❌ Reject",
                            key=f"reject_{draft_id}",
                            disabled=not reviewer_email,
                            use_container_width=True,
                        )

                        if reject_clicked:
                            st.session_state[f"show_reject_{draft_id}"] = True

                        if st.session_state.get(f"show_reject_{draft_id}"):
                            notes = st.text_area(
                                "Rejection reason (at least 10 characters)",
                                key=f"reject_notes_{draft_id}",
                                placeholder=(
                                    "e.g. Tone too formal for this student; the "
                                    "reference to the deadline is wrong."
                                ),
                                height=100,
                            )
                            confirm, cancel = st.columns(2)
                            if confirm.button(
                                "Confirm reject",
                                key=f"confirm_reject_{draft_id}",
                                use_container_width=True,
                            ):
                                if len(notes.strip()) < 10:
                                    st.error("Please give at least 10 characters.")
                                else:
                                    try:
                                        from app.nudges import reject_draft
                                        reject_draft(
                                            draft_id,
                                            reviewer_id=reviewer_email,
                                            notes=notes.strip(),
                                        )
                                        st.session_state.pop(f"show_reject_{draft_id}", None)
                                        st.success(f"Rejected draft {draft_id[:8]}…")
                                        st.cache_resource.clear()
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Reject failed: {e}")
                            if cancel.button(
                                "Cancel",
                                key=f"cancel_reject_{draft_id}",
                                use_container_width=True,
                            ):
                                st.session_state.pop(f"show_reject_{draft_id}", None)
                                st.rerun()

                        if approve_clicked:
                            try:
                                from app.nudges import send_approved_draft
                                send_approved_draft(draft_id, reviewer_id=reviewer_email)
                                st.success(f"Approved and sent draft {draft_id[:8]}…")
                                st.cache_resource.clear()
                                st.rerun()
                            except Exception as e:
                                st.error(f"Send failed: {e}")

                    with col_right:
                        st.markdown("**AI-generated draft**")
                        st.markdown(f"**Subject:** {row['subject']}")
                        st.markdown("---")
                        st.markdown(row["html_body"], unsafe_allow_html=True)

                st.markdown("")

    # ── SUB-TAB: AUDIT LOG ───────────────────────────────────────────
    with audit_tab:
        st.subheader("Audit log")
        st.caption(
            "Every action taken on a draft — creation, approval, sending, "
            "rejection — is logged as an append-only row here."
        )

        status_options = {
            "All": None,
            "Pending review": "pending_review",
            "Approved": "approved",
            "Sent": "sent",
            "Rejected": "rejected",
            "Failed": "failed",
        }

        col_f, col_l = st.columns([2, 1])
        with col_f:
            status_label = st.selectbox(
                "Filter by status", list(status_options.keys()), index=0
            )
        with col_l:
            limit = st.number_input(
                "Rows to show", min_value=10, max_value=500, value=100, step=10
            )

        status_filter = status_options[status_label]
        where = "WHERE delivery_status = %s" if status_filter else ""
        params = (status_filter, int(limit)) if status_filter else (int(limit),)

        audit_df = get_df(f"""
            SELECT nudge_id, draft_id, user_id, flag_code, nudge_type,
                   delivery_status, reviewer_id, review_notes,
                   provider_message_id, langsmith_run_id,
                   delivered_at, created_at
            FROM nudge_events
            {where}
            ORDER BY nudge_id DESC
            LIMIT %s
        """, params)

        if audit_df.empty:
            st.info("No rows for that filter.")
        else:
            st.caption(f"Showing {len(audit_df)} row{'s' if len(audit_df) != 1 else ''}.")

            status_icons = {
                "pending_review": "🟡",
                "approved": "🔵",
                "sent": "🟢",
                "rejected": "⚪",
                "failed": "🔴",
            }

            for _, row in audit_df.iterrows():
                icon = status_icons.get(row["delivery_status"], "·")
                created = row["created_at"]
                if hasattr(created, "astimezone"):
                    created_display = created.astimezone(LOCAL_TZ).strftime("%b %d, %H:%M")
                else:
                    created_display = str(created)[:16]

                header = (
                    f"{icon} **{row['delivery_status'].replace('_', ' ')}**  "
                    f"·  Student {row['user_id']}  "
                    f"·  {row['nudge_type'].replace('_', ' ')}  "
                    f"·  flag `{row['flag_code'] or '—'}`  "
                    f"·  {created_display}"
                )

                with st.popover(header):
                    left, right = st.columns([1, 1])
                    with left:
                        st.markdown(f"**Draft ID:** `{str(row['draft_id'])[:8]}…`")
                        st.markdown(f"**Reviewer:** {row['reviewer_id'] or '—'}")
                        if row["provider_message_id"]:
                            st.markdown(
                                f"**Resend msg ID:** `{row['provider_message_id']}`"
                            )
                        if pd.notna(row["delivered_at"]):
                            delivered = row["delivered_at"]
                            if hasattr(delivered, "astimezone"):
                                delivered_display = delivered.astimezone(LOCAL_TZ).strftime("%b %d, %H:%M")
                            else:
                                delivered_display = str(delivered)[:16]
                            st.markdown(f"**Delivered:** {delivered_display}")
                        if row["review_notes"]:
                            st.markdown("**Review notes:**")
                            st.info(row["review_notes"])

                    with right:
                        if row["langsmith_run_id"]:
                            if st.button(
                                "View prompt & output",
                                key=f"trace_{row['nudge_id']}",
                            ):
                                st.session_state[f"show_trace_{row['nudge_id']}"] = True

                            if st.session_state.get(f"show_trace_{row['nudge_id']}"):
                                try:
                                    from langsmith import Client
                                    client = Client()
                                    run = client.read_run(str(row["langsmith_run_id"]))

                                    st.markdown("**Prompt sent to LLM**")
                                    inputs = run.inputs or {}
                                    if "messages" in inputs:
                                        for msg in inputs["messages"]:
                                            role = msg.get("role", "unknown") if isinstance(msg, dict) else "unknown"
                                            content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
                                            st.markdown(f"_[{role}]_")
                                            st.code(content, language=None)
                                    else:
                                        st.code(str(inputs), language="json")

                                    st.markdown("**LLM output**")
                                    outputs = run.outputs or {}
                                    output_text = (
                                        outputs.get("content")
                                        or outputs.get("output")
                                        or str(outputs)
                                    )
                                    st.code(output_text, language=None)

                                    st.caption(f"Run ID: `{row['langsmith_run_id']}`")
                                except Exception as e:
                                    st.error(f"Trace unavailable: {e}")
                        else:
                            st.caption("No LangSmith trace for this row.")