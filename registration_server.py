#!/usr/bin/env python3
"""SoutheastCon Circuit Design Challenge - team registration

WHAT THIS PROGRAM DOES
======================


IMPORTANT OPERATING RULES
========================


REQUIREMENTS
============
* Python 3.10 or later.
* Standard library only; no pip packages are required.

RUNNING
=======


"""

import csv
import html
import ipaddress
import os
import secrets
import sqlite3

from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs, urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

DB_FILE = BASE_DIR / "teams.db"
TEAMS_FILE = BASE_DIR / "teams.txt"

PORT = 8081

# Competition start: April 16, 2027 at 2:00 PM Eastern Time.
# Change these constants if the schedule changes.
COMPETITION_YEAR = 2027
COMPETITION_MONTH = 4
COMPETITION_DAY = 16
COMPETITION_HOUR = 14
COMPETITION_MINUTE = 0

# April 16, 2027 is during Eastern Daylight Time (UTC-4).
# Fixed offset avoids requiring timezone database installation on Windows.
COMPETITION_TIMEZONE = timezone(timedelta(hours=-4), "EDT")

COMPETITION_START = datetime(
    COMPETITION_YEAR,
    COMPETITION_MONTH,
    COMPETITION_DAY,
    COMPETITION_HOUR,
    COMPETITION_MINUTE,
    tzinfo=COMPETITION_TIMEZONE
)

LOGO_FILE = BASE_DIR / "images/southeastcon_logo.png"


# ============================================================
# DATABASE
# ============================================================

def connect_db():
    db = sqlite3.connect(DB_FILE, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout = 15000")
    return db


def initialize_database():
    with connect_db() as db:
        db.execute("PRAGMA journal_mode = WAL")

        db.execute("""
            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_key TEXT NOT NULL UNIQUE,
                table_number INTEGER NOT NULL UNIQUE,
                division TEXT NOT NULL CHECK (division IN ('M', 'O')),
                university TEXT NOT NULL,
                team_name TEXT NOT NULL DEFAULT '',
                team_token TEXT NOT NULL UNIQUE,
                registered_at TEXT NOT NULL
            )
        """)

        # Only one Main team per university.
        # Multiple Open teams per university are allowed.
        db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS one_main_per_university
            ON teams(lower(trim(university)))
            WHERE division = 'M'
        """)


# ============================================================
# TEAM SOURCE FILE
#
# Format:
# M, University, Optional Team Name
# O, University, Optional Team Name
#
# Team name may be blank.
# ============================================================

def load_eligible_teams():
    teams = []

    if not TEAMS_FILE.exists():
        TEAMS_FILE.write_text("", encoding="utf-8")

    with TEAMS_FILE.open(
        "r", encoding="utf-8-sig", newline=""
    ) as file:
        reader = csv.reader(file)

        for line_number, fields in enumerate(reader, start=1):
            if not fields:
                continue

            if fields[0].strip().startswith("#"):
                continue

            if len(fields) < 2:
                continue

            division = fields[0].strip().upper()
            university = fields[1].strip()
            team_name = fields[2].strip() if len(fields) > 2 else ""

            if division not in ("M", "O") or not university:
                continue

            # Identifies a specific line in the source file.
            source_key = f"{line_number}:{division}:{university}:{team_name}"

            division_label = "Main" if division == "M" else "Open"
            label = f"{division_label} - {university}"

            if team_name:
                label += f" - {team_name}"
            else:
                label += f" - Unnamed Team (Entry {line_number})"

            teams.append({
                "source_key": source_key,
                "division": division,
                "university": university,
                "team_name": team_name,
                "label": label
            })

    # Main first, then Open; alphabetical university and team name.
    teams.sort(key=lambda team: (
        team["division"] != "M",
        team["university"].casefold(),
        team["team_name"].casefold()
    ))

    return teams


# ============================================================
# TOKEN GENERATION
# ============================================================

def new_team_token(db):
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

    while True:
        token = "".join(secrets.choice(alphabet) for _ in range(8))

        exists = db.execute(
            "SELECT 1 FROM teams WHERE team_token = ?",
            (token,)
        ).fetchone()

        if not exists:
            return token


# ============================================================
# HTML PAGE HELPER
# ============================================================

def page(title, body):
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root {{
    --navy: #071a3b;
    --blue: #123d78;
    --gold: #f2b632;
    --light: #f3f6fb;
    --ink: #17243a;
}}
* {{ box-sizing: border-box; }}
body {{
    font-family: Arial, sans-serif;
    max-width: 900px;
    margin: 0 auto;
    padding: 24px 18px 50px;
    color: var(--ink);
    background: var(--light);
}}
.header {{
    background: linear-gradient(135deg, var(--navy), var(--blue));
    color: white;
    border-bottom: 5px solid var(--gold);
    border-radius: 16px;
    padding: 22px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 22px;
    text-align: left;
}}
.header img {{
    width: 150px;
    height: 150px;
    object-fit: contain;
    border-radius: 12px;
    background: white;
}}
.header h1 {{
    margin: 0;
    font-size: clamp(22px, 4vw, 34px);
    line-height: 1.15;
}}
.header .subtitle {{
    margin-top: 9px;
    color: #f7d98b;
    font-size: 16px;
    font-weight: bold;
}}
.content {{
    background: white;
    margin-top: 20px;
    padding: 24px;
    border-radius: 14px;
    box-shadow: 0 3px 14px rgba(7, 26, 59, 0.09);
}}
h2 {{ color: var(--navy); margin-top: 0; }}
.stats {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    margin: 18px 0;
}}
.stat {{
    text-align: center;
    border: 1px solid #dce3ee;
    border-top: 4px solid var(--gold);
    border-radius: 10px;
    padding: 15px 8px;
    background: #fbfcff;
}}
.stat .number {{
    display: block;
    font-size: 32px;
    font-weight: bold;
    color: var(--navy);
}}
.stat .label {{
    display: block;
    margin-top: 4px;
    font-size: 13px;
    color: #52627a;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: .5px;
}}
.countdown {{
    background: var(--navy);
    color: white;
    border-radius: 12px;
    padding: 18px;
    text-align: center;
    margin: 18px 0 24px;
}}
.countdown .caption {{
    color: #f7d98b;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 1px;
    font-size: 13px;
}}
.countdown .digits {{
    font-size: clamp(25px, 5vw, 40px);
    font-weight: bold;
    font-variant-numeric: tabular-nums;
    margin-top: 8px;
}}
.countdown .date {{
    font-size: 13px;
    color: #d7e1f2;
    margin-top: 6px;
}}
label {{
    display: block;
    margin-top: 20px;
    font-weight: bold;
    color: var(--navy);
}}
input, select, button {{
    box-sizing: border-box;
    width: 100%;
    padding: 13px;
    margin-top: 7px;
    font-size: 16px;
    border-radius: 7px;
}}
input, select {{
    border: 1px solid #bdc9d9;
    background: white;
}}
button {{
    border: 0;
    background: var(--blue);
    color: white;
    font-weight: bold;
    cursor: pointer;
}}
button:hover {{ background: var(--navy); }}
.error {{ color: #b00020; font-weight: bold; }}
.success {{ color: #176b32; font-weight: bold; }}
.token {{
    display: inline-block;
    font-size: 32px;
    font-weight: bold;
    letter-spacing: 4px;
    color: var(--navy);
    background: #fff5d8;
    border: 2px dashed var(--gold);
    border-radius: 10px;
    padding: 12px 20px;
}}
.footer {{
    text-align: center;
    color: #66758a;
    font-size: 12px;
    margin-top: 18px;
}}
@media (max-width: 600px) {{
    .header {{ flex-direction: column; text-align: center; }}
    .header img {{ width: 125px; height: 125px; }}
    .content {{ padding: 18px; }}
    .stats {{ gap: 7px; }}
    .stat .number {{ font-size: 26px; }}
    .stat .label {{ font-size: 11px; }}
}}
</style>
</head>
<body>
<header class="header">
    <img src="/logo" alt="IEEE SoutheastCon 2027 logo">
    <div>
        <h1>IEEE 2027 SoutheastCon<br>Circuit Design</h1>
        <div class="subtitle">Team Registration</div>
    </div>
</header>
<main class="content">
{body}
</main>
<div class="footer">IEEE 2027 SoutheastCon Circuit Design Challenge</div>
</body>
</html>"""

# ============================================================
# HTTP HANDLER
# ============================================================

class RegistrationHandler(BaseHTTPRequestHandler):

    def is_local_request(self):
        """True only for requests originating on this computer."""
        try:
            return ipaddress.ip_address(
                self.client_address[0]
            ).is_loopback
        except ValueError:
            return False

    def send_html(self, content, status=200):
        data = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, data, status=200):
        import json

        output = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(output)))
        self.end_headers()
        self.wfile.write(output)

    def show_logo(self):
        if not LOGO_FILE.exists():
            self.send_html(
                page("Logo Not Found", "<p>southeastcon_logo.png is missing.</p>"),
                404
            )
            return

        data = LOGO_FILE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    def read_form(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8")
        return {
            key: values[0]
            for key, values in parse_qs(raw).items()
        }

    # --------------------------------------------------------
    # GET ROUTES
    # --------------------------------------------------------

    def do_GET(self):
        route = urlsplit(self.path).path.rstrip("/") or "/"

        if route == "/logo":
            self.show_logo()

        elif route == "/register":
            self.show_registration()

        elif route == "/admin":
            if not self.is_local_request():
                self.send_html(
                    page("Access Denied", "<p>Local access only.</p>"),
                    403
                )
                return
            self.show_admin()

        elif route == "/teams":
            if not self.is_local_request():
                self.send_json({"error": "Local access only"}, 403)
                return
            self.show_teams_json()

        else:
            self.send_html(
                page("Not Found", "<p>Page not found.</p>"),
                404
            )

    # --------------------------------------------------------
    # REGISTRATION PAGE
    # --------------------------------------------------------

    def show_registration(self, message=""):
        eligible = load_eligible_teams()

        options = "".join(
            f'<option value="{html.escape(team["source_key"], quote=True)}">'
            f'{html.escape(team["label"])}</option>'
            for team in eligible
        )

        if not options:
            options = (
                '<option value="">No eligible teams available</option>'
            )

        with connect_db() as db:
            counts = db.execute("""
                SELECT
                    SUM(CASE WHEN division = 'M' THEN 1 ELSE 0 END) AS main_count,
                    SUM(CASE WHEN division = 'O' THEN 1 ELSE 0 END) AS open_count,
                    COUNT(*) AS total_count
                FROM teams
            """).fetchone()

        main_count = counts["main_count"] or 0
        open_count = counts["open_count"] or 0
        total_count = counts["total_count"] or 0

        start_iso = COMPETITION_START.isoformat()
        # Windows strftime does not support %-I; use %I and
        # remove the leading zero from the hour portably.
        start_display = COMPETITION_START.strftime(
            "%A, %B %d, %Y at %I:%M %p %Z"
        )
        start_display = start_display.replace(" at 0", " at ", 1)

        body = f"""
        <h2>Competition Countdown</h2>

        <section class="countdown">
            <div class="caption" id="countdown-caption">
                Time until competition begins
            </div>
            <div class="digits" id="countdown">--d --:--:--</div>
            <div class="date">{html.escape(start_display)}</div>
        </section>

        <h2>Teams Registered</h2>
        <section class="stats">
            <div class="stat">
                <span class="number">{main_count}</span>
                <span class="label">Main</span>
            </div>
            <div class="stat">
                <span class="number">{open_count}</span>
                <span class="label">Open</span>
            </div>
            <div class="stat">
                <span class="number">{total_count}</span>
                <span class="label">Total</span>
            </div>
        </section>

        <h2>Register Your Team</h2>
        {message}

        <form method="POST" action="/submit-registration">
            <label>Table Number</label>
            <input type="number" name="table_number" min="1" required>

            <label>Team</label>
            <select name="source_key" required>
                <option value="">Select your team</option>
                {options}
            </select>

            <button type="submit">Register Team</button>
        </form>

        <script>
        (function() {{
            const target = new Date("{start_iso}").getTime();
            const display = document.getElementById("countdown");
            const caption = document.getElementById("countdown-caption");

            function updateCountdown() {{
                const remaining = target - Date.now();

                if (remaining <= 0) {{
                    display.textContent = "00d 00:00:00";
                    caption.textContent = "Competition has begun";
                    return;
                }}

                const days = Math.floor(remaining / 86400000);
                const hours = Math.floor((remaining % 86400000) / 3600000);
                const minutes = Math.floor((remaining % 3600000) / 60000);
                const seconds = Math.floor((remaining % 60000) / 1000);

                display.textContent =
                    String(days).padStart(2, "0") + "d " +
                    String(hours).padStart(2, "0") + ":" +
                    String(minutes).padStart(2, "0") + ":" +
                    String(seconds).padStart(2, "0");
            }}

            updateCountdown();
            setInterval(updateCountdown, 1000);
        }})();
        </script>
        """

        self.send_html(page("IEEE 2027 SoutheastCon Circuit Design", body))

    # --------------------------------------------------------
    # POST ROUTES
    # --------------------------------------------------------

    def do_POST(self):
        route = urlsplit(self.path).path.rstrip("/") or "/"

        if route == "/submit-registration":
            self.submit_registration()

        elif route == "/admin/add-team":
            if not self.is_local_request():
                self.send_html(
                    page("Access Denied", "<p>Local access only.</p>"),
                    403
                )
                return
            self.add_team()

        else:
            self.send_html(
                page("Not Found", "<p>Page not found.</p>"),
                404
            )

    # --------------------------------------------------------
    # SUBMIT REGISTRATION
    # --------------------------------------------------------

    def submit_registration(self):
        form = self.read_form()

        try:
            table_number = int(form.get("table_number", ""))
            if table_number < 1:
                raise ValueError
        except ValueError:
            self.show_registration(
                '<p class="error">Enter a valid positive table number.</p>'
            )
            return

        source_key = form.get("source_key", "")
        eligible = load_eligible_teams()

        selected = next(
            (team for team in eligible
             if team["source_key"] == source_key),
            None
        )

        if selected is None:
            self.show_registration(
                '<p class="error">Invalid team selection. Please try again.</p>'
            )
            return

        try:
            with connect_db() as db:
                db.execute("BEGIN IMMEDIATE")
                token = new_team_token(db)
                registered_at = datetime.now(timezone.utc).isoformat()

                db.execute("""
                    INSERT INTO teams (
                        source_key,
                        table_number,
                        division,
                        university,
                        team_name,
                        team_token,
                        registered_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    source_key,
                    table_number,
                    selected["division"],
                    selected["university"],
                    selected["team_name"],
                    token,
                    registered_at
                ))

        except sqlite3.IntegrityError:
            with connect_db() as db:
                table_exists = db.execute(
                    "SELECT 1 FROM teams WHERE table_number = ?",
                    (table_number,)
                ).fetchone()

                source_exists = db.execute(
                    "SELECT 1 FROM teams WHERE source_key = ?",
                    (source_key,)
                ).fetchone()

                main_exists = None
                if selected["division"] == "M":
                    main_exists = db.execute("""
                        SELECT 1 FROM teams
                        WHERE division = 'M'
                        AND lower(trim(university)) = lower(trim(?))
                    """, (selected["university"],)).fetchone()

            if table_exists:
                error = "That table number is already registered."
            elif source_exists:
                error = "That team has already registered."
            elif main_exists:
                error = (
                    "A Main team from this university "
                    "is already registered."
                )
            else:
                error = "Registration could not be completed."

            self.show_registration(
                f'<p class="error">{html.escape(error)}</p>'
            )
            return

        division_label = (
            "Main" if selected["division"] == "M" else "Open"
        )

        body = f"""
        <p class="success">Registration successful!</p>
        <p><b>Table:</b> {table_number}</p>
        <p><b>Division:</b> {division_label}</p>
        <p><b>University:</b> {html.escape(selected["university"])}</p>
        <p><b>Team:</b> {html.escape(selected["team_name"])}</p>
        <p>Your team token is:</p>
        <p class="token">{token}</p>
        <p>Please keep this token for competition submissions.</p>

        <form method="GET" action="/register">
            <button type="submit">Register Another Team</button>
        </form>
        """

        self.send_html(page("Registration Complete", body))

    # --------------------------------------------------------
    # ORGANIZER PAGE
    # --------------------------------------------------------

    def show_admin(self):
        body = """
        <form method="POST" action="/admin/add-team">
            <label>Division</label>
            <select name="division" required>
                <option value="M">Main</option>
                <option value="O">Open</option>
            </select>

            <label>University</label>
            <input type="text" name="university" required>

            <label>Team Name (optional)</label>
            <input type="text" name="team_name">

            <button type="submit">Add Eligible Team</button>
        </form>
        """
        self.send_html(page("Organizer - Add Late Team", body))

    # --------------------------------------------------------
    # ADD LATE TEAM
    # --------------------------------------------------------

    def add_team(self):
        form = self.read_form()

        division = form.get("division", "").strip().upper()
        university = form.get("university", "").strip()
        team_name = form.get("team_name", "").strip()

        if division not in ("M", "O") or not university:
            self.send_html(page(
                "Invalid Entry",
                '<p class="error">Division and university are required.</p>'
            ))
            return

        # Prevent adding a second Main entry for the same university.
        if division == "M":
            existing_main = next(
                (
                    team for team in load_eligible_teams()
                    if team["division"] == "M"
                    and team["university"].casefold()
                        == university.casefold()
                ),
                None
            )

            if existing_main:
                self.send_html(page(
                    "Main Team Already Listed",
                    """
                    <p class="error">
                        A Main team for this university already exists
                        in teams.txt.
                    </p>
                    <form method="GET" action="/admin">
                        <button type="submit">Go Back</button>
                    </form>
                    """
                ))
                return

        # Append safely even if the existing file has no final newline.
        needs_newline = False

        if TEAMS_FILE.exists():
            with TEAMS_FILE.open("rb") as file:
                file.seek(0, os.SEEK_END)

                if file.tell() > 0:
                    file.seek(-1, os.SEEK_END)
                    last_byte = file.read(1)
                    needs_newline = last_byte not in (b"\n", b"\r")

        with TEAMS_FILE.open(
            "a", encoding="utf-8", newline=""
        ) as file:
            if needs_newline:
                file.write("\n")

            writer = csv.writer(file)
            writer.writerow([division, university, team_name])

        print(f"Late team added to: {TEAMS_FILE}")

        body = f"""
        <p class="success">Team added successfully!</p>
        <p><b>Division:</b> {html.escape(division)}</p>
        <p><b>University:</b> {html.escape(university)}</p>
        <p><b>Team:</b> {html.escape(team_name)}</p>
        <p><b>Updated file:</b></p>
        <p>{html.escape(str(TEAMS_FILE))}</p>

        <form method="GET" action="/admin">
            <button type="submit">Add Another Team</button>
        </form>

        <form method="GET" action="/register">
            <button type="submit">Return to Registration</button>
        </form>
        """

        self.send_html(page("Team Added", body))

    # --------------------------------------------------------
    # LOCAL JSON ROSTER
    # --------------------------------------------------------

    def show_teams_json(self):
        with connect_db() as db:
            rows = db.execute("""
                SELECT
                    id,
                    table_number,
                    division,
                    university,
                    team_name,
                    team_token,
                    registered_at
                FROM teams
                ORDER BY registered_at DESC, id DESC
            """).fetchall()

        teams = [dict(row) for row in rows]

        main_count = sum(
            team["division"] == "M" for team in teams
        )
        open_count = sum(
            team["division"] == "O" for team in teams
        )

        last_updated = (
            teams[0]["registered_at"] if teams else None
        )

        self.send_json({
            "last_updated": last_updated,
            "total_main_teams": main_count,
            "total_open_teams": open_count,
            "total_teams": len(teams),
            "teams": teams
        })


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":
    initialize_database()

    print()
    print("=" * 55)
    print("REGISTRATION SERVER")
    print("=" * 55)
    print(f"Database: {DB_FILE}")
    print(f"Team list: {TEAMS_FILE}")
    print(f"Logo file: {LOGO_FILE}")
    print(f"Competition start: {COMPETITION_START.isoformat()}")
    print(f"Listening on port {PORT}")
    print()
    print(f"Registration: http://localhost:{PORT}/register")
    print(f"Organizer:    http://127.0.0.1:{PORT}/admin")
    print(f"Roster API:   http://127.0.0.1:{PORT}/teams")
    print()
    print("Admin and roster endpoints accept local requests only.")
    print("=" * 55)
    print()

    server = ThreadingHTTPServer(
        ("0.0.0.0", PORT),
        RegistrationHandler
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nRegistration server stopping.")
    finally:
        server.server_close()
