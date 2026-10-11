"""Diagnostic: tests the Google Sheets connection step by step.

Run with the same venv/Python as the app:
    python test_sheet.py
"""

import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent


def load_env():
    for line in (BASE / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()

CRED_FILE = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", str(BASE / "credentials.json"))
SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "").strip()

print("=" * 60)
print("STEP 1/4  Checking credentials.json")
try:
    info = json.loads(Path(CRED_FILE).read_text(encoding="utf-8"))
except FileNotFoundError:
    raise SystemExit(f"  FAIL: no file at {CRED_FILE}\n  -> Download the service-account JSON key and save it here as 'credentials.json'.")
except json.JSONDecodeError as e:
    raise SystemExit(f"  FAIL: credentials.json is not valid JSON ({e}).\n  -> Re-download the key; don't edit it by hand.")

if info.get("type") != "service_account":
    raise SystemExit(
        "  FAIL: this is NOT a service-account key (type=%r).\n"
        "  -> It's likely an 'OAuth 2.0 Client ID' file. Create the right one at:\n"
        "     https://console.cloud.google.com/iam-admin/serviceaccounts" % info.get("type")
    )
SA_EMAIL = info["client_email"]
print(f"  OK: service-account key")
print(f"      client_email = {SA_EMAIL}")

print("=" * 60)
print("STEP 2/4  Checking GOOGLE_SHEET_ID")
if not SHEET_ID:
    raise SystemExit("  FAIL: GOOGLE_SHEET_ID is empty in .env")
print(f"  OK: {SHEET_ID}")

print("=" * 60)
print("STEP 3/4  Authorizing with Google")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
from google.oauth2.service_account import Credentials

try:
    creds = Credentials.from_service_account_file(CRED_FILE, scopes=SCOPES)
    print("  OK: credentials loaded")
except Exception as e:
    raise SystemExit(f"  FAIL: {e}\n  -> The key file is corrupted or revoked; create a new key.")

print("=" * 60)
print("STEP 4/4  Opening the sheet and writing a test row")
from datetime import datetime, timezone

import gspread

client = gspread.authorize(creds)
try:
    sh = client.open_by_key(SHEET_ID)
except gspread.exceptions.SpreadsheetNotFound:
    raise SystemExit(
        "  FAIL: Google says this spreadsheet does not exist / is not visible.\n"
        "  -> MOST LIKELY: you haven't SHARED the sheet with the service account.\n"
        f"     Open your sheet -> Share -> add {SA_EMAIL} as Editor.\n"
        "  -> ALSO CHECK: the ID in .env matches the one in the sheet URL:\n"
        "     docs.google.com/spreadsheets/d/<ID>/edit"
    )
except gspread.exceptions.PermissionError:
    raise SystemExit(
        "  FAIL: permission denied by Google.\n"
        f"  -> Share the sheet with {SA_EMAIL} (Editor).\n"
        "  -> And enable both APIs:\n"
        "     https://console.cloud.google.com/apis/library/sheets.googleapis.com\n"
        "     https://console.cloud.google.com/apis/library/drive.googleapis.com"
    )
except Exception as e:
    msg = str(e)
    if "has not been used" in msg or "disabled" in msg:
        raise SystemExit(
            "  FAIL: an API is not enabled for your project. Enable BOTH:\n"
            "     https://console.cloud.google.com/apis/library/sheets.googleapis.com\n"
            "     https://console.cloud.google.com/apis/library/drive.googleapis.com\n"
            f"  (raw error: {msg[:300]})"
        )
    raise SystemExit(f"  FAIL while opening sheet: {msg[:500]}")

ws = sh.sheet1
print(f"  OK: opened sheet '{sh.title}' (tab '{ws.title}')")

if not ws.row_values(1):
    ws.insert_row(["Timestamp (UTC)", "Name", "Email", "Phone", "Address", "Message"], index=1)
    print("  OK: added header row to empty sheet")

row = [
    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    "TEST ROW", "test@example.com", "+251900000000",
    "Delete me", "Written by test_sheet.py",
]
try:
    ws.append_row(row, value_input_option="USER_ENTERED")
except Exception as e:
    raise SystemExit(
        f"  FAIL: could open the sheet but could NOT write: {str(e)[:300]}\n"
        f"  -> Share the sheet with {SA_EMAIL} as Editor (not Viewer/Commenter)."
    )

print("  OK: test row written!!")
print("=" * 60)
print("ALL GOOD - your Flask app will now save to Google Sheets.")
print("Go check the spreadsheet: the TEST ROW is at the bottom.")
