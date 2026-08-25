import asyncio
import time
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from playwright.async_api import async_playwright

from agent_graph import AgentNodes, AgentState, build_graph
from config import AppConfig
from gmail_otp import get_gmail_service, wait_for_otp
from llm_evaluator import build_evaluator
from notifications import build_notifier


def make_otp_provider(cfg, gmail_service):
    async def provider():
        since = int(time.time()) - 5  # only accept emails from this moment on
        return await asyncio.to_thread(
            wait_for_otp, gmail_service, cfg.erp_otp_sender, since
        )
    return provider


async def main():
    cfg = AppConfig.from_env()
    resume_text = Path(cfg.resume_file).read_text(encoding="utf-8")
    gmail = get_gmail_service(cfg.gmail_credentials_file, cfg.gmail_token_file)
    evaluate_fn = build_evaluator(resume_text, model_name=cfg.llm_model)
    notify_fn = build_notifier(cfg)

    initial: AgentState = {
        "available_jobs": [], "evaluated_jobs": [],
        "applied_jobs": [], "errors": [], "summary": "",
    }

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=cfg.headless)
        page = await browser.new_page()
        nodes = AgentNodes(
            page=page, cfg=cfg, evaluate_fn=evaluate_fn,
            otp_provider=make_otp_provider(cfg, gmail), notify_fn=notify_fn,
        )
        try:
            if cfg.require_approval:
                # Pause before "apply" so a human can approve the matches.
                graph = build_graph(nodes, checkpointer=MemorySaver(),
                                    interrupt_before=["apply"])
                thread = {"configurable": {"thread_id": "job-agent-run"}}
                await graph.ainvoke(initial, thread)
                snap = await graph.aget_state(thread)
                if snap.next:  # paused -> there is at least one match
                    print("\n=== Matched jobs ===")
                    for e in snap.values["evaluated_jobs"]:
                        if e.evaluation.is_match:
                            print(f"  * {e.job.company} | {e.job.role}\n    {e.evaluation.reason}")
                    if input("\nSubmit these applications? [y/N] ").strip().lower() != "y":
                        print("Aborted. Nothing was submitted.")
                        return
                    await graph.ainvoke(None, thread)
                final = (await graph.aget_state(thread)).values
            else:
                graph = build_graph(nodes)
                final = await graph.ainvoke(initial)
            print("\n" + final.get("summary", ""))
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())