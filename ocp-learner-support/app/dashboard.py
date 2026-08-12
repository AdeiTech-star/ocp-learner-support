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
                None: "No submissions"
            }.get(row["timing_trend"], row["timing_trend"] or "none yet"),
            "Last Login":  silent_str,
            "Page Views":  int(row["page_views"]) if row.get("page_views") is not None else 0,
            "Final Score": f"{row['final_score']:.1f}%" if row["final_score"] is not None and row["final_score"] > 0 else "N/A",
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
    st.markdown("#### Column guide")
    st.caption("Features marked with ƒ are calculated values — hover for the formula.")

    legend_data = {
        "Feature": [
            "Status", "Student ID", "Submitted", "Avg Timing ƒ",
            "Trend ƒ", "Last Login", "Page Views", "Final Score ƒ",
            "Hrs Canvas ƒ", "Gate Alert", "Flag Reason"
        ],
        "What it means": [
            "Overall risk level based on the most severe active flag. 🔴 Red = urgent. 🟡 Yellow = watch. 🟢 Green = on track. ✅ = completed.",
            "Canvas student ID. Names are not stored in this system.",
            "Number of assignments submitted out of 19 total.",
            "Average days relative to the deadline across all submitted assignments. Positive (+) = submitted early. Negative (−) = submitted late.",
            "Whether submission timing is getting better or worse. Compares the average timing of a student's earliest submissions to their most recent ones.",
            "How long ago the student last did anything in Canvas.",
            "Total course pages opened since enrollment.",
            "Overall course score across all 19 assignments. Unsubmitted assignments count as zero.",
            "Total hours spent in Canvas since enrollment.",
            "Warning when a known hard-concept week approaches within 7 days. Based on 5 dates from the course roadmap.",
            "The reason text from the most recent active flag.",
        ],
        "Formula / calculation": [
            "Worst active flag type in flag_events for this student",
            "From Canvas enrollment API",
            "Count of submissions where submitted_at is not null",
            "avg(deadline_date − submission_date) across all submissions. Deadline comes from the course roadmap (not Canvas — Canvas has no due dates for this course).",
            "Split submissions in half by order. Compare avg(first half timing) vs avg(second half timing). Improving = second half is >1 day earlier. Worsening = second half is >1 day later. Stable = within 1 day. Insufficient data = fewer than 3 submissions.",
            "Days since enrollments.last_activity_at (from Canvas enrollments API)",
            "From Canvas analytics/student_summaries endpoint",
            "From Canvas enrollments endpoint as final_score. Computed by Canvas as weighted sum across all 19 assignments.",
            "enrollments.total_activity_time (seconds) ÷ 3600",
            "gate_calendar.gate_date within 7 days of today. Five gates: SVD (6 Jul), M1 Lab (13 Jul), Backpropagation (20 Jul), Bayes Theorem (3 Aug), Entropy/KL Divergence (10 Aug).",
            "From flag_events.reason, most recent unresolved flag for this student",
        ]
    }
    legend_df = pd.DataFrame(legend_data)
    st.dataframe(legend_df, use_container_width=True, hide_index=True)

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
        st.caption("These signals are computed after each pipeline run and drive the flagging engine. Hover over column headers for descriptions.")
        st.dataframe(risk_df, use_container_width=True, hide_index=True)

        st.markdown("#### Risk signal guide")
        drill_legend = {
            "Signal": [
                "Avg Days from Deadline", "Trend", "Days Since Login",
                "Total Submissions", "Zero Submissions", "Engagement Ratio ƒ",
                "Gate Approaching", "Days Until Gate"
            ],
            "What it means": [
                "Average days early or late across all submissions. Positive = early, negative = late.",
                "Whether timing is improving or worsening. Compares first half of submissions to second half.",
                "Days since the student last did anything in Canvas.",
                "Total number of assignments submitted.",
                "1 if the student has submitted nothing at all, 0 otherwise.",
                "This student's page views relative to the most engaged student in the cohort.",
                "1 if a hard-concept gate week falls within the next 7 days, 0 otherwise.",
                "Days until the next approaching gate. Only shown when Gate Approaching = 1.",
            ],
            "Formula": [
                "avg(deadline − submitted_at) in days across all submitted assignments",
                "avg(first half timing) vs avg(second half timing). Improving if second half is >1d earlier.",
                "today − enrollments.last_activity_at in days",
                "Count of submissions where submitted_at is not null",
                "1 if total_submissions = 0, else 0",
                "student page_views ÷ max(page_views) across all students in cohort",
                "1 if any gate_calendar.gate_date is within 7 days of today",
                "gate_calendar.gate_date − today in days",
            ]
        }
        drill_df = pd.DataFrame(drill_legend)
        st.dataframe(drill_df, use_container_width=True, hide_index=True)

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
    st.title("Approval Queue")
    st.markdown("Human-in-the-loop review: AI-drafted emails appear here for approval before anything is sent to a student.")

    st.warning("**Under construction.** The layout below shows exactly how this page will work once the AI agent is connected. All buttons are disabled until then.", icon="🔧")

    st.markdown("---")

    # Pull real open flags to populate the mockup with real data
    open_flags = get_df("""
        SELECT f.flag_id, f.user_id, f.flag_type, f.reason, f.flagged_at,
               e.last_activity_at,
               r.total_submissions, r.avg_days_from_deadline, r.days_since_last_login
        FROM flag_events f
        LEFT JOIN student_risk_signals r ON f.user_id = r.user_id
        LEFT JOIN enrollments e ON f.user_id = e.user_id
        WHERE f.resolved = 0
        ORDER BY CASE f.flag_type WHEN 'red' THEN 0 ELSE 1 END, f.flagged_at DESC
    """)

    red_ct = len(open_flags[open_flags["flag_type"] == "red"])
    yel_ct = len(open_flags[open_flags["flag_type"] == "yellow"])

    c1, c2, c3 = st.columns(3)
    c1.metric("Awaiting Review", len(open_flags))
    c2.metric("🔴 Red (urgent)", red_ct)
    c3.metric("🟡 Yellow", yel_ct)

    st.markdown("---")
    st.subheader("Drafts awaiting review")
    st.caption("Red flags appear first. Each card shows the flag reason and a sample email draft. Once the AI agent is connected, the draft will be generated automatically by the LangChain agent using the student's actual data.")

    # Template drafts per flag type
    def make_draft(row):
        uid = row["user_id"]
        subs = int(row["total_submissions"]) if row["total_submissions"] else 0
        avg = row["avg_days_from_deadline"]
        silent = row["days_since_last_login"]
        reason = row["reason"]

        if "R1" in reason:
            return f"""Hi,

We noticed you have not logged into the AIML04: Math Foundations course recently and have not yet submitted any assignments.

We understand life can be busy, and we want to make sure you have the support you need to complete the course. If you are experiencing any difficulties — technical, personal, or with the course material — please reach out to the course team through Canvas.

The course team is here to help you succeed.

Warm regards,
The AIML04 Course Team

Please do not reply to this email as it is not monitored."""

        elif "R2" in reason or "R3" in reason:
            days_str = f"{abs(avg):.0f}" if avg else "several"
            return f"""Hi,

We wanted to check in with you about your progress in AIML04: Math Foundations. We can see that you have submitted {subs} assignment(s) so far, and some submissions have been arriving later than the weekly deadlines.

With the course wrapping up soon, we want to make sure you have everything you need to complete the remaining work. If you are finding any of the material challenging, the course resources and support channels on Canvas are available to help.

Please do reach out if there is anything we can do to support you.

Warm regards,
The AIML04 Course Team

Please do not reply to this email as it is not monitored."""

        elif "Y1b" in reason or "Y1" in reason:
            return f"""Hi,

We noticed that you have been active in the AIML04: Math Foundations course but have not yet submitted any assignments.

If you are working through the material and something is making it difficult to submit, we would love to hear from you. Sometimes there are technical or other barriers we can help resolve quickly.

Feel free to reach out through the Canvas support channels whenever you are ready.

Warm regards,
The AIML04 Course Team

Please do not reply to this email as it is not monitored."""

        else:
            return f"""Hi,

We are checking in on your progress in AIML04: Math Foundations. The system has noted some patterns in your submission timing that we wanted to flag to you early, so you have time to adjust before the course concludes.

If you need any support with the material or with managing your time around the deadlines, please use the support channels on Canvas.

Warm regards,
The AIML04 Course Team

Please do not reply to this email as it is not monitored."""

    for _, row in open_flags.iterrows():
        icon = "🔴" if row["flag_type"] == "red" else "🟡"
        with st.container(border=True):
            col_left, col_right = st.columns([1, 2])

            with col_left:
                st.markdown(f"### {icon} Student {row['user_id']}")
                st.markdown(f"**Flag:** {row['reason']}")
                st.markdown(f"**Raised:** {str(row['flagged_at'])[:16]} UTC")
                if row["total_submissions"] is not None:
                    st.markdown(f"**Submitted:** {int(row['total_submissions'])} of 19")
                if row["days_since_last_login"] is not None:
                    st.markdown(f"**Last login:** {int(row['days_since_last_login'])} days ago")

                st.markdown("---")
                st.markdown("**Actions** *(available once AI agent is connected)*")
                btn_a, btn_b = st.columns(2)
                with btn_a:
                    st.button("✅ Approve", key=f"approve_{row['flag_id']}", disabled=True)
                    st.button("❌ Reject", key=f"reject_{row['flag_id']}", disabled=True)
                with btn_b:
                    st.button("✏️ Edit", key=f"edit_{row['flag_id']}", disabled=True)
                    if row["flag_type"] == "red":
                        st.button("⚠️ Escalate", key=f"esc_{row['flag_id']}", disabled=True,
                                 help="For red flags where a direct instructor conversation is needed instead of an email")

            with col_right:
                st.markdown("**AI-generated draft** *(sample — actual draft generated by LangChain agent)*")
                draft = make_draft(row)
                st.text_area(
                    label="",
                    value=draft,
                    height=280,
                    disabled=True,
                    key=f"draft_{row['flag_id']}",
                    label_visibility="collapsed"
                )

        st.markdown("")

    st.markdown("---")
    st.markdown("#### How the approval queue works")
    how_it_works = {
        "Step": ["1. Flag raised", "2. Agent drafts", "3. Human reviews", "4. Decision", "5. Logged"],
        "What happens": [
            "Detection engine raises a flag for a student and writes to flag_events",
            "LangChain agent reads the flag and generates a personalised email using a Jinja2 template + Groq LLM",
            "Draft appears here. Reviewer reads the flag reason and the draft.",
            "Reviewer clicks Approve (send as-is), Edit (modify then send), Reject (do not send), or Escalate (direct instructor contact for red flags)",
            "Every decision is written to the audit log with the reviewer identity, any edits made, and the final text sent"
        ]
    }
    st.dataframe(pd.DataFrame(how_it_works), use_container_width=True, hide_index=True)
