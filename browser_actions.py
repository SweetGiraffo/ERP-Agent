"""Playwright DOM interactions, once past login.

IMPORTANT: The job listing / apply flow lives on a specific page inside
your ERP (e.g. a "Training & Placement" or "Internship" module) whose HTML
this repo has never seen. Log in manually, open that page, inspect the
elements, and update SELECTORS + ERP_JOBS_URL (.env) below to match. Login
itself is handled by erp_login.py and does NOT need touching.
"""
import asyncio

import requests
from playwright.async_api import Page

import erp_login
from models import Job

SELECTORS = {
    "job_table_rows": "table#jobs tbody tr",
    "job_company": "td:nth-child(1)",
    "job_role": "td:nth-child(2)",
    "job_deadline": "td:nth-child(3)",
    "view_jd_button": "button.view-jd",
    "jd_modal": ".jd-modal",
    "jd_close": ".jd-modal .close",
    "apply_button": "button.apply",
    "confirm_apply": "button.confirm-apply",
}


async def login(page: Page, cfg, get_otp) -> None:
    """Log into the IIT KGP ERP and land the Playwright `page` on an
    authenticated session.

    This drives the real SSO handshake (session token -> security question
    -> Gmail OTP -> ssoToken) over HTTP with `requests` — see erp_login.py
    for why — then copies the resulting cookies into Playwright's browser
    context so the rest of the agent (scrape/apply) can just use `page`
    normally. Finally it navigates to `cfg.erp_jobs_url`, the in-ERP page
    where jobs are listed.
    """
    session = requests.Session()

    session_token = await asyncio.to_thread(erp_login.get_session_token, session)
    question = await asyncio.to_thread(
        erp_login.get_security_question, session, cfg.erp_username
    )

    answer = cfg.erp_security_answers.get(question)
    if answer is None:
        configured = "\n".join(f"  - {q!r}" for q in cfg.erp_security_answers)
        raise RuntimeError(
            "ERP asked a security question that isn't configured in .env:\n"
            f"  {question!r}\n\n"
            f"Configured questions:\n{configured or '  (none)'}\n\n"
            "Set ERP_SECURITY_Q1/ERP_SECURITY_A1 (and _Q2/_A2, _Q3/_A3) to "
            "the exact wording of all 3 of your registered questions — "
            "ERP can ask any of them, and matching must be exact."
        )

    login_details = await asyncio.to_thread(
        erp_login.request_otp,
        session,
        roll_number=cfg.erp_username,
        password=cfg.erp_password,
        answer=answer,
        session_token=session_token,
    )

    otp = await get_otp()

    await asyncio.to_thread(erp_login.sign_in, session, login_details, otp)

    await page.context.add_cookies(erp_login.playwright_cookies(session))
    await page.goto(erp_login.HOMEPAGE_URL, wait_until="domcontentloaded")

    if cfg.erp_jobs_url:
        await page.goto(cfg.erp_jobs_url, wait_until="domcontentloaded")


async def scrape_jobs(page: Page) -> list[Job]:
    await page.wait_for_selector(SELECTORS["job_table_rows"], timeout=15_000)
    rows = page.locator(SELECTORS["job_table_rows"])
    jobs: list[Job] = []
    for i in range(await rows.count()):
        row = rows.nth(i)

        async def cell(selector: str) -> str:
            loc = row.locator(selector)
            return (await loc.inner_text()).strip() if await loc.count() else ""

        jobs.append(Job(
            job_id=str(i),
            company=await cell(SELECTORS["job_company"]),
            role=await cell(SELECTORS["job_role"]),
            deadline=await cell(SELECTORS["job_deadline"]),
        ))
    return jobs


async def read_job_description(page: Page, job_id: str) -> str:
    row = page.locator(SELECTORS["job_table_rows"]).nth(int(job_id))
    await row.locator(SELECTORS["view_jd_button"]).click()
    modal = page.locator(SELECTORS["jd_modal"])
    await modal.wait_for(state="visible", timeout=10_000)
    text = (await modal.inner_text()).strip()
    await page.locator(SELECTORS["jd_close"]).click()
    return text


async def apply_to_job(page: Page, job_id: str) -> None:
    row = page.locator(SELECTORS["job_table_rows"]).nth(int(job_id))
    await row.locator(SELECTORS["apply_button"]).click()
    confirm = page.locator(SELECTORS["confirm_apply"])
    if await confirm.count():
        await confirm.first.click()
    await page.wait_for_timeout(500)  # let any success toast render
