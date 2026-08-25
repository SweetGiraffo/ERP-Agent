
LONG_WORK project

1 files packaged

# Job Agent Web Dashboard — with Full Setup Wizard

A complete Flask dashboard for the IIT KGP ERP job agent. Features a **first-run setup wizard** that forces you to enter all credentials (including ERP password and security questions) before you can use the dashboard. Also includes a clear guide for obtaining `credentials.json` for Gmail API.

## Features

- **First-run wizard**: Blocks access until all required credentials are filled.
- **Full credential management**: ERP username, password, all 3 security Q/A, Gmail OAuth files, SMTP, Twilio, etc.
- **Dashboard**: Run agent, view status, stats, approvals, logs, summary.
- **Approval UI**: Approve/reject matched jobs in the browser.
- **Settings page**: Update non-sensitive config after setup.
- **Gmail instructions**: Built-in guide for getting `credentials.json`.

## Quick Start

1. **Install dependencies**:
   ```bash
   pip install -r requirements_web.txt
   python -m playwright install chromium
```

2. **Run the dashboard**:

```
python app.py
```
3. **Open your browser** to `http://localhost:5000`.

- The **setup wizard** will appear automatically.
- Fill in all fields (especially ERP credentials and Gmail file paths).
- Click **Save & Continue** to proceed.
4. **Get Gmail credentials** (if you don't have them):

- Follow the instructions in the setup page (or click the "How to get credentials.json" link in Settings).
- Place the downloaded `credentials.json` in the project root.
5. **Use the dashboard**:

- Click **Run Agent** → review approvals → click **Apply to Approved**.

## Environment Variables

All settings are stored in `.env`. The setup wizard writes:

- `ERP_USERNAME`, `ERP_PASSWORD`
- `ERP_SECURITY_Q1`, `ERP_SECURITY_A1`, etc.
- `ERP_JOBS_URL`, `ERP_OTP_SENDER`
- `GMAIL_CREDENTIALS_FILE`, `GMAIL_TOKEN_FILE`
- `LLM_MODEL`, `RESUME_FILE`
- Notification: SMTP, Twilio, email/WhatsApp targets
- Runtime: `REQUIRE_APPROVAL`, `HEADLESS`

## Getting Gmail credentials.json

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project and enable the **Gmail API**.
3. Create **OAuth client ID** for a **Desktop application**.
4. Download JSON and rename to `credentials.json`.
5. Place it in the project root.
6. The first agent run will open a browser for OAuth consent and generate `token.json` automatically.

## Project Structure

```
flask_dashboard/
├── app.py                  # Flask app with routes + first-run logic
├── agent_web.py            # Agent runner with web state
├── templates/
│   ├── setup.html          # First-run wizard (all credentials)
│   ├── index.html          # Dashboard
│   └── settings.html       # Settings (non-sensitive)
├── requirements_web.txt
├── run.sh / run.bat
└── README.md
```

## API Endpoints

| Method ↕▾ | Endpoint ↕▾ | Description ↕▾ |
|---|---|---|
| −GET | `/` | Dashboard (redirects to setup if first run) |
| −GET/POST | `/setup` | Setup wizard (POST saves) |
| −GET | `/settings` | Settings page |
| −GET | `/api/status` | Agent status |
| POST | `/api/run` | Start agent |
| POST | `/api/stop` | Stop agent |
| GET | `/api/approvals` | Pending approvals |
| POST | `/api/approve` | Approve job |
| POST | `/api/reject` | Reject job |
| POST | `/api/apply` | Apply to approved jobs |
| POST | `/api/reset` | Reset state |
| GET/POST | `/api/settings` | Get/update settings |
| GET | `/api/logs` | Recent logs |
| GET | `/api/gmail_instructions` | Gmail setup guide |
⚙

## Security Notes

- Credentials are stored in **plain text** in `.env`. Protect this file.
- The setup wizard does not hash passwords; they are written as-is.
- Use environment variables or a secrets manager for production.

## Troubleshooting

- **First-run loop**: Check that `.env` has all required keys (username, password, at least 1 security Q/A, gmail_credentials_file, erp_jobs_url).
- **Gmail OAuth errors**: Ensure `credentials.json` is valid and `token.json` is writable.
- **Playwright errors**: Run `python -m playwright install chromium`.
- **Missing resume**: Create a `resume.txt` file with your resume in plain text.

## License

MIT (same as the original job agent).

