# What changed

## ⚠️ Security first
Your uploaded `_env.example` had a **real roll number and password** in it
(`25ma60r29` / `Vaibhav@2002`), not placeholders. If that file was ever
committed to git, shared, or is otherwise not fully private to you, **change
your ERP password now**. The new `.env.example` only has placeholders, and
`.gitignore` now excludes `.env`, `credentials.json`, and `token.json` so
secrets can't get committed by accident.

## The real fix: login
erp.iitkgp.ac.in's login isn't a form you can just fill and submit — it's a
4-step AJAX handshake (session token → your security question → OTP email →
sign-in). The old `browser_actions.login()` tried to click through it as if
it were a normal form, which is exactly what's brittle/broken about it.

- **`erp_login.py`** (new) — talks to the same endpoints the metaKGP
  extension you linked uses (`SSOAdministration/getSecurityQues.htm`,
  `getEmilOTP.htm`, `auth.htm`), via plain `requests`, matching the protocol
  documented in `metakgp/iitkgp-erp-login-pypi`.
- **`browser_actions.login()`** — now runs that handshake, then copies the
  resulting session cookies into the Playwright browser (`page.context.add_cookies`)
  so `scrape_jobs`/`apply_to_job` keep working exactly as before.
- **`config.py`** — ERP asks a *different* one of your 3 registered security
  questions each login, so you need to configure all 3:
  `ERP_SECURITY_Q1`/`A1`, `_Q2`/`A2`, `_Q3`/`A3` (copy each question's exact
  wording from the ERP page — matching is exact-string). `ERP_OTP_SENDER`
  now defaults to `erpkgp@adm.iitkgp.ac.in`, the real sender address.
- **`test_erp_login.py`** (new) — 10 mocked-network unit tests for the new
  handshake; all pass.

## Still on you (can't be guessed from outside)
- **`ERP_JOBS_URL`** in `.env` — the in-ERP URL of wherever jobs are listed
  for you (Training & Placement module, etc). Log in manually and copy it.
- **`SELECTORS`** in `browser_actions.py` — the job table / apply button
  CSS selectors are still placeholders (`table#jobs`, `button.apply`, ...).
  Open that jobs page, inspect the actual elements, and update them —
  there's no way to know this without seeing your specific ERP module.

## Setup script
`setuprun.bat` was bash syntax (`&&`, `source`) in a `.bat` file, and never
actually installed anything. Replaced with `setup.sh` (Linux/macOS) and
`setup.bat` (Windows), both of which install `requirements.txt` **and**
Playwright's Chromium binary (`playwright install`), which the old script
was missing entirely.
