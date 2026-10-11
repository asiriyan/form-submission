"""Contact form -> Google Sheets (local CSV fallback if Sheets is not working).

Run:
    pip install -r requirements.txt
    python app.py
"""

import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv(path=BASE_DIR / ".env"):
    """Tiny .env loader so you don't need python-dotenv."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SERVICE_ACCOUNT_FILE = os.environ.get(
    "GOOGLE_SERVICE_ACCOUNT_FILE", str(BASE_DIR / "credentials.json")
)
if not Path(SERVICE_ACCOUNT_FILE).is_absolute():
    SERVICE_ACCOUNT_FILE = str(BASE_DIR / SERVICE_ACCOUNT_FILE)
SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "").strip()
SHEET_NAME = os.environ.get("GOOGLE_SHEET_NAME", "Form Submissions")
LOCAL_CSV = BASE_DIR / "submissions.csv"

HEADERS = ["Timestamp (UTC)", "Name", "Email", "Phone", "Address", "Message"]
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PHONE_RE = re.compile(r"^[+0-9][0-9 ().\-]{4,24}$")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

_worksheet = None
_sheets_error = None


def sheets_configured():
    """True if the minimum config to reach Google Sheets exists."""
    return bool(SHEET_ID) and bool(
        SERVICE_ACCOUNT_JSON or Path(SERVICE_ACCOUNT_FILE).exists()
    )


# ---------------------------------------------------------------------------
# Short, human-readable error messages
# ---------------------------------------------------------------------------
def _sa_email():
    """Return the service account email (used in 'share the sheet with...')."""
    try:
        if SERVICE_ACCOUNT_JSON:
            return json.loads(SERVICE_ACCOUNT_JSON).get("client_email", "")
        return json.loads(
            Path(SERVICE_ACCOUNT_FILE).read_text(encoding="utf-8")
        ).get("client_email", "")
    except Exception:
        return ""


def explain(exc):
    """Turn any Google/gspread error into ONE short line: 'problem -> fix'."""
    sa = _sa_email() or "<your service account email>"

    # Our own errors first
    if isinstance(exc, ImportError):
        return "Libraries missing -> run: pip install gspread google-auth"
    if isinstance(exc, FileNotFoundError):
        return (
            f"Key file not found at {SERVICE_ACCOUNT_FILE} -> download the "
            "service-account JSON key and save it as credentials.json"
        )
    if isinstance(exc, json.JSONDecodeError):
        return "Key file is not valid JSON -> re-download the key, don't edit it"
    if isinstance(exc, ValueError) and "NOT a service-account key" in str(exc):
        return (
            "This is not a service-account key (probably an OAuth client file) -> "
            "IAM & Admin > Service Accounts > Keys > Add key > JSON"
        )

    # Google API errors
    code, msg = None, str(exc)
    resp = getattr(exc, "response", None)
    if resp is not None:
        code = getattr(resp, "status_code", None)
        try:
            msg = resp.json()["error"]["message"]
        except Exception:
            msg = (getattr(resp, "text", "") or msg)[:200]
    low = msg.lower()

    if exc.__class__.__name__ == "SpreadsheetNotFound":
        return f"Sheet not found -> check GOOGLE_SHEET_ID and share the sheet with {sa} as Editor"
    if "has not been used" in low or "is disabled" in low:
        return (
            "Google API not enabled -> enable BOTH Google Sheets API and "
            "Google Drive API in Cloud Console > APIs & Services > Library"
        )
    if code == 403:
        return f"No permission (403) -> share the sheet with {sa} as EDITOR"
    if code == 404:
        return f"Sheet not found (404) -> check GOOGLE_SHEET_ID and share it with {sa} as Editor"
    if code == 429:
        return "Too many requests (429) -> wait a minute and try again"
    if "invalid_grant" in low or "invalid jwt" in low:
        return "Key rejected by Google -> create a new JSON key and check your PC date/time"
    if "getaddrinfo" in low or "connection" in low or "timed out" in low:
        return "Cannot reach Google -> check your internet connection or VPN"
    return f"Unexpected error -> {msg[:150]}"


# ---------------------------------------------------------------------------
# Google Sheets connection
# ---------------------------------------------------------------------------
REQUIRED_SA_FIELDS = {
    "type", "project_id", "client_email", "private_key", "token_uri",
}


def _service_account_credentials():
    """Load the service-account key, with a clear error for the wrong file type."""
    from google.oauth2.service_account import Credentials

    if SERVICE_ACCOUNT_JSON:
        info = json.loads(SERVICE_ACCOUNT_JSON)
        source = "GOOGLE_SERVICE_ACCOUNT_JSON"
    elif Path(SERVICE_ACCOUNT_FILE).exists():
        info = json.loads(Path(SERVICE_ACCOUNT_FILE).read_text(encoding="utf-8"))
        source = str(SERVICE_ACCOUNT_FILE)
    else:
        raise FileNotFoundError(SERVICE_ACCOUNT_FILE)

    if info.get("type") != "service_account" or not REQUIRED_SA_FIELDS.issubset(info):
        raise ValueError(f"{source} is NOT a service-account key")
    return Credentials.from_service_account_info(info, scopes=SCOPES)


def connect_google_sheets():
    """Connect once and cache the worksheet; cache a short error message."""
    global _worksheet, _sheets_error

    if _worksheet is not None:
        return _worksheet
    if not SHEET_ID:
        _sheets_error = "GOOGLE_SHEET_ID is not set -> add it to .env"
        return None
    try:
        import gspread

        creds = _service_account_credentials()
        client = gspread.authorize(creds)
        ws = client.open_by_key(SHEET_ID).sheet1
        if not ws.row_values(1):  # add the header row to a new empty sheet
            ws.insert_row(HEADERS, index=1)
        _worksheet = ws
        _sheets_error = None
    except Exception as exc:  # auth, permissions, wrong ID, offline, ...
        _sheets_error = explain(exc)
        print(f"[sheets] {_sheets_error}")  # also show it in the terminal
    return _worksheet


def safe_cell(value):
    """Prevent spreadsheet formula injection (=, +, -, @ at the start)."""
    if value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def save_submission(row):
    """Save to Google Sheets if possible; otherwise fall back to a local CSV.

    Returns "google-sheets" or "local-csv".
    """
    global _worksheet, _sheets_error
    ws = connect_google_sheets()
    if ws is not None:
        try:
            ws.append_row(row, value_input_option="USER_ENTERED")
            return "google-sheets"
        except Exception as exc:  # force reconnect on next submission
            _sheets_error = explain(exc)
            print(f"[sheets] {_sheets_error}")
            _worksheet = None

    new_file = not LOCAL_CSV.exists()
    with open(LOCAL_CSV, "a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if new_file:
            writer.writerow(HEADERS)
        writer.writerow(row)
    return "local-csv"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template(
        "index.html",
        errors={},
        values={},
        sheets_configured=sheets_configured(),
        sheet_name=SHEET_NAME,
    )


@app.route("/submit", methods=["POST"])
def submit():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    address = request.form.get("address", "").strip()
    message = request.form.get("message", "").strip()

    errors = {}
    if not name:
        errors["name"] = "Please enter your name."
    if not email:
        errors["email"] = "Please enter your email address."
    elif not EMAIL_RE.match(email):
        errors["email"] = "That doesn't look like a valid email address."
    if not phone:
        errors["phone"] = "Please enter your phone number."
    elif not PHONE_RE.match(phone):
        errors["phone"] = "Enter digits, spaces and + ( ) - only."
    if not address:
        errors["address"] = "Please enter your address."
    if not message:
        errors["message"] = "Please write a short message."

    if errors:
        return (
            render_template(
                "index.html",
                errors=errors,
                values=request.form,
                sheets_configured=sheets_configured(),
                sheet_name=SHEET_NAME,
            ),
            400,
        )

    row = [
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        safe_cell(name),
        safe_cell(email),
        safe_cell(phone),
        safe_cell(address),
        safe_cell(message),
    ]
    where = save_submission(row)

    if where == "google-sheets":
        flash(f"Thanks {name}! Your message was saved to Google Sheets.", "success")
    else:
        flash(
            f"Saved to local file (submissions.csv). Google Sheets problem: {_sheets_error}",
            "warning",
        )
    return redirect("/#form")

@app.context_processor
def inject_sheet_url():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit?usp=sharing" if SHEET_ID else ""
    return {"sheet_url": url}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)