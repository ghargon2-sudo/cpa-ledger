"""
The Ledger — CPA Study Tracker (Python / Streamlit version)

Run with:  streamlit run app.py

All your data is saved automatically to a file called ledger.db
in this same folder, so it will still be there next time you open the app.
"""

import sqlite3
import datetime as dt
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).parent / "ledger.db"

SECTIONS = ["AUD", "FAR", "REG", "TCP"]

SECTION_LABELS = {
    "AUD": "Auditing & Attestation",
    "FAR": "Financial Accounting & Reporting",
    "REG": "Regulation",
    "TCP": "Tax Compliance & Planning",
}

DEFAULT_TOPICS = {
    "AUD": [
        "Ethics & Professional Responsibilities",
        "Assessing Risk & Planning Response",
        "Performing Procedures & Obtaining Evidence",
        "Forming Conclusions & Reporting",
    ],
    "FAR": [
        "Conceptual Framework & Financial Reporting",
        "Select Balance Sheet Accounts",
        "Select Transactions",
        "State & Local Governments",
    ],
    "REG": [
        "Ethics & Federal Tax Procedures",
        "Business Law",
        "Federal Taxation of Property Transactions",
        "Federal Taxation of Individuals",
        "Federal Taxation of Entities",
    ],
    "TCP": [
        "Individual Tax Compliance & Planning",
        "Entity Tax Compliance & Planning",
        "Property Transactions",
        "Business Analysis & Advisory",
    ],
}

DEFAULTS = {
    "AUD": {"exam_date": "2026-09-07", "study_start": "2026-07-20", "target_hours": 100},
    "FAR": {"exam_date": "2027-01-15", "study_start": "", "target_hours": 120},
    "REG": {"exam_date": "", "study_start": "", "target_hours": 100},
    "TCP": {"exam_date": "", "study_start": "", "target_hours": 80},
}


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sections (
            name TEXT PRIMARY KEY,
            exam_date TEXT,
            study_start TEXT,
            target_hours REAL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section TEXT,
            name TEXT,
            done INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section TEXT,
            date TEXT,
            hours REAL,
            topic TEXT,
            notes TEXT
        )
    """)
    conn.commit()

    # Seed defaults only if the sections table is empty (first run)
    cur.execute("SELECT COUNT(*) FROM sections")
    if cur.fetchone()[0] == 0:
        for s in SECTIONS:
            d = DEFAULTS[s]
            cur.execute(
                "INSERT INTO sections (name, exam_date, study_start, target_hours) VALUES (?, ?, ?, ?)",
                (s, d["exam_date"], d["study_start"], d["target_hours"]),
            )
            for topic_name in DEFAULT_TOPICS[s]:
                cur.execute(
                    "INSERT INTO topics (section, name, done) VALUES (?, ?, 0)",
                    (s, topic_name),
                )
        conn.commit()

    conn.close()


def get_section(section):
    conn = get_conn()
    row = conn.execute(
        "SELECT exam_date, study_start, target_hours FROM sections WHERE name = ?", (section,)
    ).fetchone()
    conn.close()
    return {"exam_date": row[0] or "", "study_start": row[1] or "", "target_hours": row[2] or 0}


def update_section(section, exam_date, study_start, target_hours):
    conn = get_conn()
    conn.execute(
        "UPDATE sections SET exam_date = ?, study_start = ?, target_hours = ? WHERE name = ?",
        (exam_date, study_start, target_hours, section),
    )
    conn.commit()
    conn.close()


def get_topics(section):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, name, done FROM topics WHERE section = ? ORDER BY id", (section,)
    ).fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "done": bool(r[2])} for r in rows]


def toggle_topic(topic_id, done):
    conn = get_conn()
    conn.execute("UPDATE topics SET done = ? WHERE id = ?", (1 if done else 0, topic_id))
    conn.commit()
    conn.close()


def get_sessions(section):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, date, hours, topic, notes FROM sessions WHERE section = ? ORDER BY date DESC, id DESC",
        (section,),
    ).fetchall()
    conn.close()
    return [{"id": r[0], "date": r[1], "hours": r[2], "topic": r[3], "notes": r[4]} for r in rows]


def add_session(section, date, hours, topic, notes):
    conn = get_conn()
    conn.execute(
        "INSERT INTO sessions (section, date, hours, topic, notes) VALUES (?, ?, ?, ?, ?)",
        (section, date, hours, topic, notes),
    )
    conn.commit()
    conn.close()


def delete_session(session_id):
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()


def hours_logged(section):
    conn = get_conn()
    row = conn.execute("SELECT SUM(hours) FROM sessions WHERE section = ?", (section,)).fetchone()
    conn.close()
    return row[0] or 0


# ---------------------------------------------------------------------------
# Small date helpers
# ---------------------------------------------------------------------------

def parse_date(date_str):
    if not date_str:
        return None
    return dt.datetime.strptime(date_str, "%Y-%m-%d").date()


def days_until(date_str):
    d = parse_date(date_str)
    if d is None:
        return None
    return (d - dt.date.today()).days


def fmt_date(date_str):
    d = parse_date(date_str)
    if d is None:
        return "—"
    return d.strftime("%b %-d, %Y") if hasattr(d, "strftime") else str(d)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

st.set_page_config(page_title="The Ledger — CPA Tracker", page_icon="📒", layout="centered")

init_db()

# Ledger-themed styling
st.markdown("""
<style>
    .stApp { background-color: #EDEBE2; }
    .ledger-header {
        background-color: #1B2420;
        color: #EDEBE2;
        padding: 24px 20px;
        border-radius: 10px;
        margin-bottom: 20px;
    }
    .ledger-card {
        background-color: #1B2420;
        color: #EDEBE2;
        padding: 18px 20px;
        border-radius: 10px;
        margin-bottom: 18px;
    }
    .balance-number { font-size: 34px; font-weight: 700; font-family: monospace; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="ledger-header"><h1 style="margin:0;">📒 The Ledger</h1>'
            '<p style="opacity:0.7; margin:4px 0 0;">CPA Study Tracker — AUD · FAR · REG · TCP</p></div>',
            unsafe_allow_html=True)

# Upcoming exam banner
upcoming = None
for s in SECTIONS:
    d = days_until(get_section(s)["exam_date"])
    if d is not None and d >= 0 and (upcoming is None or d < upcoming[1]):
        upcoming = (s, d)

if upcoming:
    st.info(f"**{upcoming[1]} days** until **{upcoming[0]}** ({fmt_date(get_section(upcoming[0])['exam_date'])})")

tab_names = SECTIONS + ["Summary"]
tabs = st.tabs(tab_names)

for i, section in enumerate(SECTIONS):
    with tabs[i]:
        st.subheader(SECTION_LABELS[section])
        sec = get_section(section)

        col1, col2, col3 = st.columns(3)
        with col1:
            exam_date = st.date_input(
                "Exam date",
                value=parse_date(sec["exam_date"]) if sec["exam_date"] else None,
                key=f"exam_{section}",
            )
        with col2:
            study_start = st.date_input(
                "Study start",
                value=parse_date(sec["study_start"]) if sec["study_start"] else None,
                key=f"start_{section}",
            )
        with col3:
            target_hours = st.number_input(
                "Target hours", min_value=0, value=int(sec["target_hours"]), step=5, key=f"target_{section}"
            )

        new_exam_str = exam_date.isoformat() if exam_date else ""
        new_start_str = study_start.isoformat() if study_start else ""
        if (new_exam_str != sec["exam_date"] or new_start_str != sec["study_start"]
                or target_hours != sec["target_hours"]):
            update_section(section, new_exam_str, new_start_str, target_hours)
            st.rerun()

        # Balance card
        logged = hours_logged(section)
        balance = target_hours - logged
        exam_days = days_until(new_exam_str)
        start_days = days_until(new_start_str)
        days_to_use_as_start = start_days if (start_days is not None and start_days > 0) else 0
        weeks_remaining = None
        if exam_days is not None and exam_days > days_to_use_as_start:
            weeks_remaining = max(1, -(-(exam_days - days_to_use_as_start) // 7))  # ceil division
        weekly_pace = (max(0, balance) / weeks_remaining) if weeks_remaining else None

        pct = min(100, (logged / target_hours * 100)) if target_hours else 0
        balance_label = "due" if balance > 0 else "surplus"
        st.markdown(f"""
        <div class="ledger-card">
            <div style="display:flex; justify-content:space-between; opacity:0.7; font-size:12px; text-transform:uppercase;">
                <span>Hours logged</span><span>Balance {balance_label}</span>
            </div>
            <div style="display:flex; justify-content:space-between; align-items:baseline; margin-top:6px;">
                <span class="balance-number">{logged:g} <span style="font-size:15px; opacity:0.6;">/ {target_hours:g} hrs</span></span>
                <span class="balance-number" style="font-size:22px; color:{'#B8863B' if balance > 0 else '#7FBF9E'};">{abs(balance):g}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.progress(pct / 100)
        if weekly_pace is not None:
            if balance > 0:
                st.caption(f"⏱ Stay on pace at **{weekly_pace:.1f} hrs/week** over {weeks_remaining} "
                           f"week(s) to hit your target by {fmt_date(new_exam_str)}.")
            else:
                st.caption(f"✅ Target met — {abs(balance):g} hrs ahead of plan.")

        st.divider()

        # Topics checklist
        st.markdown("**Blueprint Areas**")
        topics = get_topics(section)
        done_count = sum(1 for t in topics if t["done"])
        st.caption(f"{done_count}/{len(topics)} complete")
        for t in topics:
            checked = st.checkbox(t["name"], value=t["done"], key=f"topic_{t['id']}")
            if checked != t["done"]:
                toggle_topic(t["id"], checked)
                st.rerun()

        st.divider()

        # Log a session
        st.markdown("**Log a Study Session**")
        with st.form(key=f"form_{section}", clear_on_submit=True):
            fcol1, fcol2 = st.columns(2)
            with fcol1:
                sess_date = st.date_input("Date", value=dt.date.today(), max_value=dt.date.today(), key=f"sdate_{section}")
            with fcol2:
                sess_hours = st.number_input("Hours", min_value=0.25, step=0.25, value=1.0, key=f"shours_{section}")
            topic_options = [t["name"] for t in topics] + ["MCQ review", "Simulations", "Full review"]
            sess_topic = st.selectbox("Topic", topic_options, key=f"stopic_{section}")
            sess_notes = st.text_area("Notes (optional)", key=f"snotes_{section}",
                                       placeholder="e.g. missed 8/20 MCQs on risk assessment")
            submitted = st.form_submit_button("Add to ledger")
            if submitted:
                add_session(section, sess_date.isoformat(), sess_hours, sess_topic, sess_notes)
                st.success("Session logged.")
                st.rerun()

        # Session list
        st.markdown("**Study Sessions**")
        sessions = get_sessions(section)
        if not sessions:
            st.caption(f"No sessions logged for {section} yet.")
        else:
            for s in sessions:
                c1, c2, c3 = st.columns([2, 5, 1])
                with c1:
                    st.write(fmt_date(s["date"]))
                with c2:
                    st.write(f"**{s['topic'] or 'General review'}**" + (f" — {s['notes']}" if s["notes"] else ""))
                with c3:
                    st.write(f"+{s['hours']:g}h")
                if st.button("🗑", key=f"del_{s['id']}"):
                    delete_session(s["id"])
                    st.rerun()

# Summary tab
with tabs[-1]:
    st.subheader("All Sections")
    for section in SECTIONS:
        sec = get_section(section)
        logged = hours_logged(section)
        d = days_until(sec["exam_date"])
        d_label = "no date set" if d is None else (f"{d}d out" if d >= 0 else "date passed")
        c1, c2, c3 = st.columns([1, 2, 2])
        c1.markdown(f"**{section}**")
        c2.write(f"{logged:g}/{sec['target_hours']:g} hrs")
        c3.write(d_label)
