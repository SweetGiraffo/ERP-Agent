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
