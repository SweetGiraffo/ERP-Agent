import asyncio
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from browser_actions import apply_to_job
from browser_actions import login as browser_login
from browser_actions import read_job_description, scrape_jobs
from models import EvaluatedJob, Job


class AgentState(TypedDict):
    available_jobs: list[Job]
    evaluated_jobs: list[EvaluatedJob]
    applied_jobs: list[str]
    errors: Annotated[list[str], operator.add]  # append across nodes
    summary: str


def route_after_evaluation(state: AgentState) -> str:
    if any(e.evaluation.is_match for e in state["evaluated_jobs"]):
        return "apply"
    return "notify"


def build_summary(state: AgentState) -> str:
    evaluated = state["evaluated_jobs"]
    matches = [e for e in evaluated if e.evaluation.is_match]
    lines = [
        "JOB AGENT RUN SUMMARY",
        f"Jobs found: {len(state['available_jobs'])}",
        f"Evaluated: {len(evaluated)} | Matches: {len(matches)}",
        "",
    ]
    for e in evaluated:
        tag = "MATCH" if e.evaluation.is_match else "skip "
        lines.append(f"[{tag}] {e.job.company} | {e.job.role} - {e.evaluation.reason}")
    lines.append(f"\nApplied ({len(state['applied_jobs'])}):")
    lines += [f"  * {a}" for a in state["applied_jobs"]]
    if state["errors"]:
        lines.append("\nErrors:")
        lines += [f"  ! {err}" for err in state["errors"]]
    return "\n".join(lines)


class AgentNodes:
    """Dependencies are injected so nodes are unit-testable without a browser."""

    def __init__(self, page, cfg, evaluate_fn, otp_provider, notify_fn):
        self.page = page
        self.cfg = cfg
        self.evaluate_fn = evaluate_fn
        self.otp_provider = otp_provider
        self.notify_fn = notify_fn

    async def login(self, state: AgentState) -> dict:
        await browser_login(self.page, self.cfg, self.otp_provider)
        return {}

    async def scrape(self, state: AgentState) -> dict:
        return {"available_jobs": await scrape_jobs(self.page)}

    async def evaluate(self, state: AgentState) -> dict:
        evaluated, errors = [], []
        for job in state["available_jobs"]:
            try:
                job.description = await read_job_description(self.page, job.job_id)
            except Exception as exc:
                errors.append(f"JD scrape failed for {job.company}: {exc}")
            try:
                result = await self.evaluate_fn(job)
                evaluated.append(EvaluatedJob(job=job, evaluation=result))
            except Exception as exc:
                errors.append(f"LLM evaluation failed for {job.company}: {exc}")
        return {"evaluated_jobs": evaluated, "errors": errors}

    async def apply(self, state: AgentState) -> dict:
        applied, errors = [], []
        for item in state["evaluated_jobs"]:
            if not item.evaluation.is_match:
                continue
            try:
                await apply_to_job(self.page, item.job.job_id)
                applied.append(f"{item.job.company} - {item.job.role}")
            except Exception as exc:
                errors.append(f"Apply failed for {item.job.company}: {exc}")
        return {"applied_jobs": applied, "errors": errors}

    async def notify(self, state: AgentState) -> dict:
        summary = build_summary(state)
        await asyncio.to_thread(self.notify_fn, summary)
        return {"summary": summary}


def build_graph(nodes: AgentNodes, checkpointer=None, interrupt_before=None):
    graph = StateGraph(AgentState)
    graph.add_node("login", nodes.login)
    graph.add_node("scrape", nodes.scrape)
    graph.add_node("evaluate", nodes.evaluate)
    graph.add_node("apply", nodes.apply)
    graph.add_node("notify", nodes.notify)

    graph.add_edge(START, "login")
    graph.add_edge("login", "scrape")
    graph.add_edge("scrape", "evaluate")
    graph.add_conditional_edges(
        "evaluate", route_after_evaluation, {"apply": "apply", "notify": "notify"}
    )
    graph.add_edge("apply", "notify")
    graph.add_edge("notify", END)

    kwargs = {}
    if checkpointer:
        kwargs["checkpointer"] = checkpointer
    if interrupt_before:
        kwargs["interrupt_before"] = interrupt_before
    return graph.compile(**kwargs)