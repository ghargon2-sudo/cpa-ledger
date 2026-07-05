"""
The Ledger — CPA Study Tracker (Python / Streamlit version)
Guy Hargon — LSU MAcc + KPMG Houston

Run with:  streamlit run app.py

All your data is saved automatically to a file called ledger.db
in this same folder, so it will still be there next time you open the app.
"""

import sqlite3
import json
import calendar as cal
import datetime as dt
from pathlib import Path

import streamlit as st
import pandas as pd

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

CONFIDENCE_OPTIONS = ["Guessing", "Unsure", "Confident"]
REVIEW_INTERVALS_DAYS = [1, 3, 7, 14]  # how far out to schedule a re-review after N misses
SCORE_VALID_MONTHS = 18


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _column_exists(conn, table, column):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    return column in cols


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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS question_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section TEXT,
            topic TEXT,
            notes TEXT,
            questions_json TEXT,
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS question_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_set_id INTEGER,
            question_index INTEGER,
            section TEXT,
            topic TEXT,
            miss_count INTEGER DEFAULT 0,
            correct_streak INTEGER DEFAULT 0,
            next_review_date TEXT,
            last_confidence TEXT,
            last_correct INTEGER,
            last_attempted TEXT,
            UNIQUE(question_set_id, question_index)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS question_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_set_id INTEGER,
            question_index INTEGER,
            section TEXT,
            topic TEXT,
            correct INTEGER,
            confidence TEXT,
            attempted_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            date TEXT,
            category TEXT
        )
    """)
    conn.commit()

    # Migrate older sections table (add passed / pass_date if missing)
    if not _column_exists(conn, "sections", "passed"):
        cur.execute("ALTER TABLE sections ADD COLUMN passed INTEGER DEFAULT 0")
    if not _column_exists(conn, "sections", "pass_date"):
        cur.execute("ALTER TABLE sections ADD COLUMN pass_date TEXT")
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM sections")
    if cur.fetchone()[0] == 0:
        for s in SECTIONS:
            d = DEFAULTS[s]
            cur.execute(
                "INSERT INTO sections (name, exam_date, study_start, target_hours, passed, pass_date) "
                "VALUES (?, ?, ?, ?, 0, NULL)",
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
        "SELECT exam_date, study_start, target_hours, passed, pass_date FROM sections WHERE name = ?",
        (section,),
    ).fetchone()
    conn.close()
    return {
        "exam_date": row[0] or "",
        "study_start": row[1] or "",
        "target_hours": row[2] or 0,
        "passed": bool(row[3]),
        "pass_date": row[4] or "",
    }


def update_section(section, exam_date, study_start, target_hours):
    conn = get_conn()
    conn.execute(
        "UPDATE sections SET exam_date = ?, study_start = ?, target_hours = ? WHERE name = ?",
        (exam_date, study_start, target_hours, section),
    )
    conn.commit()
    conn.close()


def update_section_passed(section, passed, pass_date):
    conn = get_conn()
    conn.execute(
        "UPDATE sections SET passed = ?, pass_date = ? WHERE name = ?",
        (1 if passed else 0, pass_date, section),
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


def get_all_sessions():
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, section, date, hours, topic, notes FROM sessions ORDER BY date DESC, id DESC"
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "section": r[1], "date": r[2], "hours": r[3], "topic": r[4], "notes": r[5]}
        for r in rows
    ]


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


def save_question_set(section, topic, notes, questions):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO question_sets (section, topic, notes, questions_json, created_at) VALUES (?, ?, ?, ?, ?)",
        (section, topic, notes, json.dumps(questions), dt.datetime.now().isoformat()),
    )
    qset_id = cur.lastrowid
    for idx in range(len(questions)):
        conn.execute(
            "INSERT OR IGNORE INTO question_state (question_set_id, question_index, section, topic) "
            "VALUES (?, ?, ?, ?)",
            (qset_id, idx, section, topic),
        )
    conn.commit()
    conn.close()


def get_question_sets(section=None):
    conn = get_conn()
    if section:
        rows = conn.execute(
            "SELECT id, section, topic, notes, questions_json, created_at FROM question_sets "
            "WHERE section = ? ORDER BY id DESC",
            (section,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, section, topic, notes, questions_json, created_at FROM question_sets ORDER BY id DESC"
        ).fetchall()
    conn.close()
    return [
        {"id": r[0], "section": r[1], "topic": r[2], "notes": r[3],
         "questions": json.loads(r[4]), "created_at": r[5]}
        for r in rows
    ]


def delete_question_set(qs_id):
    conn = get_conn()
    conn.execute("DELETE FROM question_sets WHERE id = ?", (qs_id,))
    conn.execute("DELETE FROM question_state WHERE question_set_id = ?", (qs_id,))
    conn.execute("DELETE FROM question_attempts WHERE question_set_id = ?", (qs_id,))
    conn.commit()
    conn.close()


def record_attempt(qset_id, q_index, section, topic, correct, confidence):
    today_str = dt.date.today().isoformat()
    conn = get_conn()
    conn.execute(
        "INSERT INTO question_attempts (question_set_id, question_index, section, topic, correct, "
        "confidence, attempted_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (qset_id, q_index, section, topic, 1 if correct else 0, confidence, dt.datetime.now().isoformat()),
    )
    row = conn.execute(
        "SELECT miss_count, correct_streak FROM question_state WHERE question_set_id = ? AND question_index = ?",
        (qset_id, q_index),
    ).fetchone()
    miss_count = row[0] if row else 0
    correct_streak = row[1] if row else 0

    if correct:
        correct_streak += 1
        next_review = None  # mastered for now
    else:
        miss_count += 1
        correct_streak = 0
        interval = REVIEW_INTERVALS_DAYS[min(miss_count - 1, len(REVIEW_INTERVALS_DAYS) - 1)]
        next_review = (dt.date.today() + dt.timedelta(days=interval)).isoformat()

    conn.execute(
        "INSERT INTO question_state (question_set_id, question_index, section, topic, miss_count, "
        "correct_streak, next_review_date, last_confidence, last_correct, last_attempted) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(question_set_id, question_index) DO UPDATE SET "
        "miss_count=excluded.miss_count, correct_streak=excluded.correct_streak, "
        "next_review_date=excluded.next_review_date, last_confidence=excluded.last_confidence, "
        "last_correct=excluded.last_correct, last_attempted=excluded.last_attempted",
        (qset_id, q_index, section, topic, miss_count, correct_streak, next_review,
         confidence, 1 if correct else 0, today_str),
    )
    conn.commit()
    conn.close()


def get_due_questions():
    """Returns question refs whose spaced-repetition review is due today or overdue."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT question_set_id, question_index, section, topic, miss_count FROM question_state "
        "WHERE next_review_date IS NOT NULL AND next_review_date <= ? ORDER BY next_review_date",
        (dt.date.today().isoformat(),),
    ).fetchall()
    conn.close()
    due = []
    qset_cache = {}
    for qset_id, q_index, section, topic, miss_count in rows:
        if qset_id not in qset_cache:
            qsets = [q for q in get_question_sets() if q["id"] == qset_id]
            qset_cache[qset_id] = qsets[0] if qsets else None
        qset = qset_cache[qset_id]
        if qset and q_index < len(qset["questions"]):
            due.append({
                "qset_id": qset_id,
                "q_index": q_index,
                "section": section,
                "topic": topic,
                "miss_count": miss_count,
                "question": qset["questions"][q_index],
            })
    return due


def get_weak_areas():
    conn = get_conn()
    rows = conn.execute(
        "SELECT section, topic, correct, confidence FROM question_attempts"
    ).fetchall()
    conn.close()
    if not rows:
        return pd.DataFrame(columns=["Section", "Topic", "Attempts", "Accuracy %", "Confidently Wrong"])
    df = pd.DataFrame(rows, columns=["section", "topic", "correct", "confidence"])
    grouped = df.groupby(["section", "topic"]).agg(
        attempts=("correct", "count"),
        accuracy=("correct", "mean"),
    ).reset_index()
    grouped["accuracy"] = (grouped["accuracy"] * 100).round(0)
    conf_wrong = df[(df["confidence"] == "Confident") & (df["correct"] == 0)]
    conf_wrong_counts = conf_wrong.groupby(["section", "topic"]).size().reset_index(name="confidently_wrong")
    grouped = grouped.merge(conf_wrong_counts, on=["section", "topic"], how="left")
    grouped["confidently_wrong"] = grouped["confidently_wrong"].fillna(0).astype(int)
    grouped = grouped.sort_values("accuracy")
    grouped.columns = ["Section", "Topic", "Attempts", "Accuracy %", "Confidently Wrong"]
    return grouped


def get_events():
    conn = get_conn()
    rows = conn.execute("SELECT id, title, date, category FROM events ORDER BY date").fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "date": r[2], "category": r[3]} for r in rows]


def add_event(title, date, category):
    conn = get_conn()
    conn.execute("INSERT INTO events (title, date, category) VALUES (?, ?, ?)", (title, date, category))
    conn.commit()
    conn.close()


def delete_event(event_id):
    conn = get_conn()
    conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()


def compute_streak():
    conn = get_conn()
    dates = set()
    for row in conn.execute("SELECT DISTINCT date FROM sessions"):
        if row[0]:
            dates.add(row[0][:10])
    for row in conn.execute("SELECT DISTINCT attempted_at FROM question_attempts"):
        if row[0]:
            dates.add(row[0][:10])
    conn.close()
    date_objs = set()
    for ds in dates:
        try:
            date_objs.add(dt.datetime.strptime(ds, "%Y-%m-%d").date())
        except ValueError:
            pass
    streak = 0
    cursor_date = dt.date.today()
    if cursor_date not in date_objs:
        cursor_date -= dt.timedelta(days=1)
    while cursor_date in date_objs:
        streak += 1
        cursor_date -= dt.timedelta(days=1)
    return streak


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


def add_months(d, months):
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, cal.monthrange(year, month)[1])
    return dt.date(year, month, day)


# ---------------------------------------------------------------------------
# Practice question generation (Claude API)
# ---------------------------------------------------------------------------

def get_api_key():
    try:
        if "ANTHROPIC_API_KEY" in st.secrets:
            return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        pass
    return st.session_state.get("anthropic_api_key", "")


def generate_questions(section, topic, notes, num_questions, model, api_key):
    """
    Calls the Claude API to generate original practice questions based on the
    student's own notes. This never sends or reproduces any third-party
    course material - only what the student personally typed in.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    prompt = f"""You are helping a CPA exam candidate quiz themselves on the {section} \
section ({SECTION_LABELS[section]}), topic: "{topic}".

Below are the student's own personal study notes on this topic. Using ONLY the concepts \
in these notes as a jumping-off point, write {num_questions} original multiple-choice \
practice questions in the style of the CPA exam. Each question should test understanding \
of the underlying accounting/auditing/tax concept, not just recall of the note text.

Student's notes:
\"\"\"
{notes}
\"\"\"

Respond with ONLY valid JSON (no markdown fences, no preamble) matching this exact shape:
[
  {{
    "question": "...",
    "choices": ["...", "...", "...", "..."],
    "correct_index": 0,
    "explanation": "..."
  }}
]
"""

    response = client.messages.create(
        model=model,
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in response.content if hasattr(block, "text"))
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

st.set_page_config(page_title="The Ledger — CPA Tracker", page_icon="📒", layout="centered")

init_db()

if "dark_mode" not in st.session_state:
    st.session_state["dark_mode"] = False

DARK = st.session_state["dark_mode"]

if DARK:
    page_bg = "#12160F"
    card_bg = "#1E2A24"
    text_color = "#EDEBE2"
    line = "#33403A"
else:
    page_bg = "#EDEBE2"
    card_bg = "#FAF9F4"
    text_color = "#1B2420"
    line = "#D8D4C6"

ink_bg = "#1B2420"
paper = "#EDEBE2"
green = "#2F6B4F"
rust = "#A6432E"
gold = "#B8863B"
mint = "#7FBF9E"

st.markdown(f"""
<style>
    .stApp {{ background-color: {page_bg}; color: {text_color}; }}
    .ledger-header {{
        background-color: {ink_bg};
        color: {paper};
        padding: 24px 20px;
        border-radius: 10px;
        margin-bottom: 16px;
    }}
    .ledger-card {{
        background-color: {ink_bg};
        color: {paper};
        padding: 18px 20px;
        border-radius: 10px;
        margin-bottom: 18px;
    }}
    .balance-number {{ font-size: 34px; font-weight: 700; font-family: monospace; }}
    .streak-pill {{
        display: inline-block; background-color: {gold}; color: {ink_bg};
        padding: 4px 12px; border-radius: 999px; font-weight: 700; font-size: 13px;
    }}
</style>
""", unsafe_allow_html=True)

# --- Sidebar ---------------------------------------------------------------
with st.sidebar:
    st.markdown("### Settings")
    dark_toggle = st.toggle("Dark mode", value=st.session_state["dark_mode"])
    if dark_toggle != st.session_state["dark_mode"]:
        st.session_state["dark_mode"] = dark_toggle
        st.rerun()

    streak = compute_streak()
    st.markdown(f'<span class="streak-pill">🔥 {streak}-day streak</span>', unsafe_allow_html=True)

    st.markdown("### Export Data")
    all_sessions = get_all_sessions()
    if all_sessions:
        df_sessions = pd.DataFrame(all_sessions)
        st.download_button(
            "Download sessions (CSV)",
            df_sessions.to_csv(index=False).encode("utf-8"),
            file_name="ledger_sessions.csv",
            mime="text/csv",
        )
    conn = get_conn()
    attempt_rows = conn.execute(
        "SELECT section, topic, correct, confidence, attempted_at FROM question_attempts ORDER BY attempted_at"
    ).fetchall()
    conn.close()
    if attempt_rows:
        df_attempts = pd.DataFrame(
            attempt_rows, columns=["section", "topic", "correct", "confidence", "attempted_at"]
        )
        st.download_button(
            "Download question results (CSV)",
            df_attempts.to_csv(index=False).encode("utf-8"),
            file_name="ledger_question_results.csv",
            mime="text/csv",
        )
    if not all_sessions and not attempt_rows:
        st.caption("Log a session or answer a question to unlock exports.")

# --- Header ------------------------------------------------------------
st.markdown('<div class="ledger-header"><h1 style="margin:0;">📒 The Ledger</h1>'
            '<p style="opacity:0.7; margin:4px 0 0;">Guy Hargon · LSU MAcc · KPMG Houston</p></div>',
            unsafe_allow_html=True)

# Upcoming exam banner
upcoming = None
for s in SECTIONS:
    d = days_until(get_section(s)["exam_date"])
    if d is not None and d >= 0 and (upcoming is None or d < upcoming[1]):
        upcoming = (s, d)

if upcoming:
    st.info(f"**{upcoming[1]} days** until **{upcoming[0]}** ({fmt_date(get_section(upcoming[0])['exam_date'])})")

# Score expiration banner
passed_sections = [s for s in SECTIONS if get_section(s)["passed"] and get_section(s)["pass_date"]]
unpassed_exam_dates = [
    parse_date(get_section(s)["exam_date"])
    for s in SECTIONS
    if not get_section(s)["passed"] and get_section(s)["exam_date"]
]
if passed_sections:
    for s in passed_sections:
        sec = get_section(s)
        pass_date = parse_date(sec["pass_date"])
        expiration = add_months(pass_date, SCORE_VALID_MONTHS)
        days_left = (expiration - dt.date.today()).days
        conflict = unpassed_exam_dates and max(unpassed_exam_dates) > expiration
        msg = f"**{s}** score expires **{fmt_date(expiration.isoformat())}** ({days_left} days left)"
        if conflict:
            st.error(msg + " — this is BEFORE your latest scheduled remaining exam. Re-sequence your plan.")
        elif days_left < 120:
            st.warning(msg)
        else:
            st.caption(msg)

tab_names = SECTIONS + ["Practice Questions", "Weak Areas", "Calendar", "Summary"]
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

        pcol1, pcol2 = st.columns([1, 2])
        with pcol1:
            passed_checked = st.checkbox("Passed this section", value=sec["passed"], key=f"passed_{section}")
        pass_date_val = None
        if passed_checked:
            with pcol2:
                pass_date_val = st.date_input(
                    "Pass date",
                    value=parse_date(sec["pass_date"]) if sec["pass_date"] else dt.date.today(),
                    key=f"passdate_{section}",
                )
        new_pass_date_str = pass_date_val.isoformat() if pass_date_val else ""
        if passed_checked != sec["passed"] or new_pass_date_str != (sec["pass_date"] or ""):
            update_section_passed(section, passed_checked, new_pass_date_str or None)
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
                <span class="balance-number" style="font-size:22px; color:{gold if balance > 0 else mint};">{abs(balance):g}</span>
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


def render_question(qset_id, idx, q, key_prefix):
    """Shared UI for answering a single question with a confidence rating,
    used both for freshly generated sets and for spaced-repetition review."""
    st.markdown(f"**{q['question']}**")
    confidence = st.radio(
        "How confident are you?", CONFIDENCE_OPTIONS, key=f"conf_{key_prefix}", horizontal=True,
    )
    choice = st.radio(
        "Choose an answer", q["choices"], key=f"ans_{key_prefix}", index=None, label_visibility="collapsed",
    )
    result_key = f"result_{key_prefix}"
    if st.button("Submit answer", key=f"submit_{key_prefix}"):
        if choice is None:
            st.warning("Pick an answer first.")
        else:
            chosen_index = q["choices"].index(choice)
            correct = chosen_index == q["correct_index"]
            record_attempt(qset_id, idx, q.get("_section"), q.get("_topic"), correct, confidence)
            st.session_state[result_key] = {"correct": correct, "explanation": q["explanation"],
                                             "correct_choice": q["choices"][q["correct_index"]]}
    if result_key in st.session_state:
        r = st.session_state[result_key]
        if r["correct"]:
            st.success(f"Correct! {r['explanation']}")
        else:
            st.error(f"Not quite. Correct answer: **{r['correct_choice']}**. {r['explanation']}")
    st.markdown("---")


# Practice Questions tab
with tabs[len(SECTIONS)]:
    st.subheader("Practice Questions from Your Notes")
    st.caption(
        "Type what you just studied in your own words, and Claude will write fresh, "
        "original practice questions to test your understanding — nothing here is "
        "pulled from Becker or any other course material."
    )

    api_key = get_api_key()
    if not api_key:
        st.info(
            "This feature needs an Anthropic API key (separate from a claude.ai account). "
            "Get one at console.anthropic.com — API keys are billed by usage, and question "
            "generation typically costs a fraction of a cent each with the default model."
        )
        entered_key = st.text_input("Anthropic API key", type="password", key="key_input")
        if entered_key:
            st.session_state["anthropic_api_key"] = entered_key
            st.rerun()
    else:
        due = get_due_questions()
        if due:
            st.markdown(f"### 🔁 Due for Review ({len(due)})")
            st.caption("Questions you've missed before, resurfacing on a spaced-repetition schedule.")
            for d in due:
                q = dict(d["question"])
                q["_section"] = d["section"]
                q["_topic"] = d["topic"]
                render_question(d["qset_id"], d["q_index"], q, f"due_{d['qset_id']}_{d['q_index']}")
            st.divider()

        st.markdown("### Generate New Questions")
        pq_col1, pq_col2 = st.columns(2)
        with pq_col1:
            pq_section = st.selectbox("Section", SECTIONS, key="pq_section")
        with pq_col2:
            pq_topic = st.text_input("Topic", key="pq_topic", placeholder="e.g. Revenue recognition")

        pq_notes = st.text_area(
            "Your notes",
            key="pq_notes",
            height=140,
            placeholder="Summarize what you just learned in your own words...",
        )

        adv = st.expander("Advanced options")
        with adv:
            pq_num = st.slider("Number of questions", 1, 10, 5, key="pq_num")
            pq_model = st.selectbox(
                "Model",
                ["claude-haiku-4-5-20251001", "claude-sonnet-5"],
                key="pq_model",
                help="Haiku is cheaper and fast; Sonnet gives higher-quality, harder questions.",
            )
            if st.button("Forget saved API key"):
                st.session_state.pop("anthropic_api_key", None)
                st.rerun()

        if st.button("Generate questions", type="primary"):
            if not pq_notes.strip():
                st.warning("Add a few notes first so there's something to quiz you on.")
            else:
                with st.spinner("Writing your practice questions..."):
                    try:
                        qs = generate_questions(
                            pq_section, pq_topic or "General", pq_notes, pq_num, pq_model, api_key
                        )
                        save_question_set(pq_section, pq_topic or "General", pq_notes, qs)
                        st.success(f"Generated {len(qs)} questions.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Couldn't generate questions: {e}")

        st.divider()
        st.markdown("### Your Question Sets")
        all_sets = get_question_sets()
        if not all_sets:
            st.caption("No question sets yet — generate your first one above.")
        for qset in all_sets:
            with st.expander(f"{qset['section']} · {qset['topic']} · {fmt_date(qset['created_at'][:10])}"):
                for i, q in enumerate(qset["questions"]):
                    qq = dict(q)
                    qq["_section"] = qset["section"]
                    qq["_topic"] = qset["topic"]
                    render_question(qset["id"], i, qq, f"set_{qset['id']}_{i}")
                if st.button("Delete this set", key=f"delqs_{qset['id']}"):
                    delete_question_set(qset["id"])
                    st.rerun()

# Weak Areas tab
with tabs[len(SECTIONS) + 1]:
    st.subheader("Weak Areas")
    st.caption("Built from your answered practice questions across all sections.")
    weak_df = get_weak_areas()
    if weak_df.empty:
        st.caption("Answer some practice questions to populate this view.")
    else:
        st.dataframe(weak_df, use_container_width=True, hide_index=True)
        confidently_wrong = weak_df[weak_df["Confidently Wrong"] > 0]
        if not confidently_wrong.empty:
            st.warning(
                "⚠️ Confidently wrong — topics where you felt sure but missed the question. "
                "These are your most dangerous gaps:\n\n" +
                "\n".join(
                    f"- **{r['Section']} · {r['Topic']}**: {int(r['Confidently Wrong'])} time(s)"
                    for _, r in confidently_wrong.iterrows()
                )
            )
        lowest = weak_df[weak_df["Attempts"] >= 3].head(3)
        if not lowest.empty:
            st.markdown("**Lowest accuracy (3+ attempts):**")
            for _, r in lowest.iterrows():
                st.write(f"- {r['Section']} · {r['Topic']} — {r['Accuracy %']:.0f}% ({int(r['Attempts'])} attempts)")

# Calendar tab
with tabs[len(SECTIONS) + 2]:
    st.subheader("Calendar — CPA + LSU")
    st.caption("Track LSU coursework deadlines alongside your CPA study plan in one place.")

    with st.form("add_event_form", clear_on_submit=True):
        ecol1, ecol2, ecol3 = st.columns([3, 2, 2])
        with ecol1:
            ev_title = st.text_input("Title", placeholder="e.g. Tax final exam")
        with ecol2:
            ev_date = st.date_input("Date", value=dt.date.today())
        with ecol3:
            ev_category = st.selectbox("Category", ["LSU", "CPA", "Other"])
        if st.form_submit_button("Add to calendar"):
            if ev_title.strip():
                add_event(ev_title, ev_date.isoformat(), ev_category)
                st.success("Added.")
                st.rerun()
            else:
                st.warning("Give it a title first.")

    st.divider()
    st.markdown("**Upcoming**")

    combined = []
    for e in get_events():
        combined.append({"title": e["title"], "date": e["date"], "category": e["category"], "id": e["id"], "deletable": True})
    for s in SECTIONS:
        sec = get_section(s)
        if sec["exam_date"]:
            combined.append({"title": f"{s} Exam", "date": sec["exam_date"], "category": "CPA", "id": None, "deletable": False})

    combined = [c for c in combined if days_until(c["date"]) is not None and days_until(c["date"]) >= -1]
    combined.sort(key=lambda c: c["date"])

    category_icon = {"LSU": "🎓", "CPA": "📒", "Other": "📌"}
    if not combined:
        st.caption("Nothing upcoming — add a deadline or class date above.")
    for c in combined:
        d = days_until(c["date"])
        if d > 0:
            day_label = f"({d}d out)"
        elif d == 0:
            day_label = "(today)"
        else:
            day_label = "(1d ago)"
        col1, col2 = st.columns([6, 1])
        with col1:
            st.write(f"{category_icon.get(c['category'], '📌')} **{c['title']}** — {fmt_date(c['date'])} {day_label}")
        with col2:
            if c["deletable"] and st.button("🗑", key=f"delev_{c['id']}"):
                delete_event(c["id"])
                st.rerun()

# Summary tab
with tabs[-1]:
    st.subheader("All Sections")
    for section in SECTIONS:
        sec = get_section(section)
        logged = hours_logged(section)
        d = days_until(sec["exam_date"])
        d_label = "no date set" if d is None else (f"{d}d out" if d >= 0 else "date passed")
        status = " ✅ passed" if sec["passed"] else ""
        c1, c2, c3 = st.columns([1, 2, 2])
        c1.markdown(f"**{section}**{status}")
        c2.write(f"{logged:g}/{sec['target_hours']:g} hrs")
        c3.write(d_label)

    st.divider()
    st.markdown("### Last 7 Days")

    today = dt.date.today()
    last_7 = [today - dt.timedelta(days=n) for n in range(6, -1, -1)]

    conn = get_conn()
    hours_rows = conn.execute(
        "SELECT date, SUM(hours) FROM sessions WHERE date >= ? GROUP BY date",
        ((today - dt.timedelta(days=6)).isoformat(),),
    ).fetchall()
    attempt_rows = conn.execute(
        "SELECT substr(attempted_at,1,10) as d, SUM(correct), COUNT(*) FROM question_attempts "
        "WHERE substr(attempted_at,1,10) >= ? GROUP BY d",
        ((today - dt.timedelta(days=6)).isoformat(),),
    ).fetchall()
    conn.close()

    hours_by_date = {r[0]: r[1] for r in hours_rows}
    accuracy_by_date = {r[0]: (r[1] / r[2] * 100 if r[2] else None) for r in attempt_rows}

    digest_df = pd.DataFrame({
        "Date": [d.strftime("%m/%d") for d in last_7],
        "Hours": [hours_by_date.get(d.isoformat(), 0) or 0 for d in last_7],
    }).set_index("Date")
    st.bar_chart(digest_df)

    acc_values = [accuracy_by_date.get(d.isoformat()) for d in last_7]
    if any(v is not None for v in acc_values):
        acc_df = pd.DataFrame({
            "Date": [d.strftime("%m/%d") for d in last_7],
            "Accuracy %": [v if v is not None else 0 for v in acc_values],
        }).set_index("Date")
        st.line_chart(acc_df)
    else:
        st.caption("Answer some practice questions this week to see an accuracy trend here.")
