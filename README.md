# Form → Google Sheets (Python / Flask)

A contact form with **name, email, phone number, address and message** fields.
On submit, the data is appended as a new row in a Google Sheet (with a UTC
timestamp). Until you add your Google credentials it automatically falls back
to a local `submissions.csv` file, so you can test everything right away.

```
form-sheets-app/
├── app.py                # Flask app: form, validation, Google Sheets writer
├── templates/index.html  # The form page
├── static/style.css      # Styling
├── requirements.txt
├── .env.example          # Config template (copy to .env)
└── README.md
```

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000 — the form works immediately in **demo mode**
(saved to `submissions.csv`).

## Connect it to Google Sheets (5 minutes)

1. **Create a Google Cloud project**
   Go to https://console.cloud.google.com → *New Project*.

2. **Enable APIs**
   In *APIs & Services → Library*, enable:
   - **Google Sheets API**
   - **Google Drive API**

3. **Create a service account + key**
   *IAM & Admin → Service Accounts → Create Service Account* → give it any name
   → then open it → *Keys → Add Key → Create new key → JSON*.
   Save the downloaded file as **`credentials.json`** in this project folder.

4. **Create a Google Sheet and share it**
   - Create a spreadsheet (e.g. "Form Submissions").
   - Open the `credentials.json` file and copy the `client_email` value
     (looks like `form-bot@my-project.iam.gserviceaccount.com`).
   - In the sheet, click **Share** and add that email as **Editor**.

5. **Configure and run**

   ```bash
   cp .env.example .env
   # edit .env and paste your GOOGLE_SHEET_ID
   # (the long ID inside the sheet URL: docs.google.com/spreadsheets/d/<ID>/edit)
   python app.py
   ```

   The green status banner on the form will confirm it's delivering to your
   sheet. New submissions land as rows:
   `Timestamp (UTC) | Name | Email | Phone | Address | Message`.

### Deploying / env vars instead of files

Instead of a `credentials.json` file you can set
`GOOGLE_SERVICE_ACCOUNT_JSON` to the full JSON content of the key (handy on
Heroku/Railway/etc.). All config keys:

| Variable | Purpose |
|---|---|
| `GOOGLE_SHEET_ID` | Spreadsheet ID (**required**) |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Path to key JSON (default `credentials.json`) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Key JSON as a string (alternative to the file) |
| `GOOGLE_SHEET_NAME` | Label shown on the form |
| `SECRET_KEY` | Flask session secret |
| `PORT` | Server port (default `5000`) |

## Common setup errors

- **`missing fields token_uri, client_email`** → you downloaded an
  *OAuth 2.0 Client ID* file instead of a service-account key. Get the correct
  file from **IAM & Admin → Service Accounts → (your account) → Keys → Add Key
  → Create new key → JSON**. A valid key contains `"type": "service_account"`,
  plus `client_email`, `private_key` and `token_uri`.
- **`The caller does not have permission` / sheet opens but rows fail** → you
  didn't share the Google Sheet with the service account's `client_email`.
- **`Requested entity was not found`** → wrong `GOOGLE_SHEET_ID` (copy it from
  the sheet URL, not the file name).

## Notes

- The header row is added automatically if the sheet is empty.
- Inputs starting with `=`, `+`, `-` or `@` are escaped to protect the sheet
  from formula injection.
- If Google Sheets is unreachable, submissions are saved to
  `submissions.csv` instead of being lost.
- Never commit `credentials.json` — it's already in `.gitignore`.
