"""Web-compatible agent runner with approval management."""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from datetime import datetime

from langgraph.checkpoint.memory import MemorySaver
from playwright.async_api import async_playwright

from agent_graph import AgentNodes, AgentState, build_graph, build_summary
from config import AppConfig
from gmail_otp import get_gmail_service, wait_for_otp
from llm_evaluator import build_evaluator
from notifications import build_notifier

class AgentStatus(Enum):
    """Status of the agent run."""

    IDLE = "idle"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    APPLYING = "applying"
    DONE = "done"
    ERROR = "error"
    STOPPED = "stopped"

@dataclass
class JobApproval:
    """A job awaiting approval."""

    job_id: str
    company: str
    role: str
    deadline: str
    description: str
    reason: str
    is_match: bool
    approved: Optional[bool] = None  # True=approved, False=rejected, None=pending

@dataclass
class AgentRunState:
    """State of a single agent run."""

    status: AgentStatus = AgentStatus.IDLE
    thread_id: str = ""
    evaluated_jobs: List[Dict[str, Any]] = field(default_factory=list)
    approvals: Dict[str, JobApproval] = field(default_factory=dict)
    applied_jobs: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    summary: str = ""
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error: Optional[str] = None
    stop_requested: bool = False
    logs: List[str] = field(default_factory=list)

class AgentWebRunner:
    """Manages the agent lifecycle with web integration."""

    def __init__(self):
        self.state = AgentRunState()
        self._graph = None
        self._thread = None
        self._cfg = None
        self._nodes = None
        self._page = None
        self._browser = None
        self._playwright = None
        self._gmail = None

    @property
    def status(self) -> AgentStatus:
        return self.state.status

    @status.setter
    def status(self, value: AgentStatus):
        self.state.status = value
        self._add_log(f"Status: {value.value}")

    @property
    def stop_requested(self) -> bool:
        return self.state.stop_requested

    @stop_requested.setter
    def stop_requested(self, value: bool):
        self.state.stop_requested = value

    @property
    def error(self) -> Optional[str]:
        return self.state.error

    @error.setter
    def error(self, value: Optional[str]):
        self.state.error = value
        if value:
            self.status = AgentStatus.ERROR
            self._add_log(f"ERROR: {value}")

    def _add_log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.state.logs.append(f"[{timestamp}] {message}")

    def get_status(self) -> Dict[str, Any]:
        """Get the current status for the API."""
        return {
            "status": self.state.status.value,
            "thread_id": self.state.thread_id,
            "evaluated_count": len(self.state.evaluated_jobs),
            "approvals_count": len([a for a in self.state.approvals.values() if a.approved is None]),
            "approved_count": len([a for a in self.state.approvals.values() if a.approved is True]),
            "rejected_count": len([a for a in self.state.approvals.values() if a.approved is False]),
            "applied_count": len(self.state.applied_jobs),
            "errors_count": len(self.state.errors),
            "summary": self.state.summary,
            "error": self.state.error,
            "is_running": self.state.status in (AgentStatus.RUNNING, AgentStatus.AWAITING_APPROVAL, AgentStatus.APPLYING),
            "start_time": self.state.start_time.isoformat() if self.state.start_time else None,
            "end_time": self.state.end_time.isoformat() if self.state.end_time else None,
            "logs": self.state.logs[-50:],  # Last 50 logs
        }

    def get_approvals(self) -> List[Dict[str, Any]]:
        """Get all jobs awaiting approval."""
        approvals = []
        for job_id, approval in self.state.approvals.items():
            if approval.approved is None:
                approvals.append({
                    "job_id": approval.job_id,
                    "company": approval.company,
                    "role": approval.role,
                    "deadline": approval.deadline,
                    "description": approval.description[:500] + "..." if len(approval.description) > 500 else approval.description,
                    "reason": approval.reason,
                    "is_match": approval.is_match,
                })
        return approvals

    def approve_job(self, job_id: str) -> Dict[str, Any]:
        """Approve a specific job."""
        if job_id in self.state.approvals:
            self.state.approvals[job_id].approved = True
            self._add_log(f"Approved: {self.state.approvals[job_id].company} - {self.state.approvals[job_id].role}")
            return {"status": "approved", "job_id": job_id}
        return {"error": "Job not found", "job_id": job_id}

    def reject_job(self, job_id: str) -> Dict[str, Any]:
        """Reject a specific job."""
        if job_id in self.state.approvals:
            self.state.approvals[job_id].approved = False
            self._add_log(f"Rejected: {self.state.approvals[job_id].company} - {self.state.approvals[job_id].role}")
            return {"status": "rejected", "job_id": job_id}
        return {"error": "Job not found", "job_id": job_id}

    def get_logs(self) -> List[str]:
        """Get all logs."""
        return self.state.logs

    async def run(self, config_override: Optional[Dict[str, Any]] = None):
        """Run the agent up to the approval point."""
        try:
            self._reset_state()
            self.status = AgentStatus.RUNNING
            self.state.start_time = datetime.now()
            self._add_log("Starting agent run...")

            # Load config
            cfg = AppConfig.from_env()
            if config_override:
                # Apply overrides (only safe fields)
                for key, value in config_override.items():
                    if hasattr(cfg, key):
                        setattr(cfg, key, value)
            self._cfg = cfg

            # Load resume
            resume_path = Path(cfg.resume_file)
            if not resume_path.exists():
                raise FileNotFoundError(f"Resume file not found: {resume_path}")
            resume_text = resume_path.read_text(encoding="utf-8")

            # Gmail service
            self._gmail = get_gmail_service(cfg.gmail_credentials_file, cfg.gmail_token_file)

            # Evaluator
            evaluate_fn = build_evaluator(resume_text, model_name=cfg.llm_model)

            # Notifier
            notify_fn = build_notifier(cfg)

            # Playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=cfg.headless)
            self._page = await self._browser.new_page()

            # OTP provider
            async def otp_provider():
                since = int(time.time()) - 5
                return await asyncio.to_thread(
                    wait_for_otp, self._gmail, cfg.erp_otp_sender, since
                )

            # Nodes
            self._nodes = AgentNodes(
                page=self._page,
                cfg=cfg,
                evaluate_fn=evaluate_fn,
                otp_provider=otp_provider,
                notify_fn=notify_fn,
            )

            # Build graph with interruption before apply
            self._graph = build_graph(
                self._nodes,
                checkpointer=MemorySaver(),
                interrupt_before=["apply"],
            )

            self.state.thread_id = f"web-run-{int(time.time())}"
            thread = {"configurable": {"thread_id": self.state.thread_id}}

            # Initial state
            initial: AgentState = {
                "available_jobs": [],
                "evaluated_jobs": [],
                "applied_jobs": [],
                "errors": [],
                "summary": "",
            }

            self._add_log("Invoking agent graph...")
            await self._graph.ainvoke(initial, thread)

            # Check if interrupted (awaiting approval)
            snap = await self._graph.aget_state(thread)
            self._thread = thread

            if snap.next:
                # We're at the apply node - waiting for approval
                self.status = AgentStatus.AWAITING_APPROVAL
                self._add_log("Agent paused - awaiting approval")

                # Extract evaluated jobs
                values = snap.values
                self.state.evaluated_jobs = values.get("evaluated_jobs", [])
                self.state.errors = values.get("errors", [])

                # Build approval list from matches
                for ej in self.state.evaluated_jobs:
                    if ej.get("evaluation", {}).get("is_match", False):
                        job = ej.get("job", {})
                        eval_data = ej.get("evaluation", {})
                        job_id = job.get("job_id", "")
                        self.state.approvals[job_id] = JobApproval(
                            job_id=job_id,
                            company=job.get("company", "Unknown"),
                            role=job.get("role", "Unknown"),
                            deadline=job.get("deadline", ""),
                            description=job.get("description", ""),
                            reason=eval_data.get("reason", "No reason provided"),
                            is_match=True,
                            approved=None,
                        )

                if not self.state.approvals:
                    # No matches - skip approval
                    self._add_log("No matches found, proceeding to notification...")
                    await self._apply_and_finish_internal(thread)
                else:
                    self._add_log(f"Found {len(self.state.approvals)} jobs awaiting approval")
                    # Keep the graph state, we'll resume when user approves

            else:
                # No interruption - done
                values = snap.values
                self.state.summary = values.get("summary", "No summary available")
                self.status = AgentStatus.DONE
                self.state.end_time = datetime.now()
                self._add_log("Agent run completed (no approvals needed)")

        except Exception as e:
            self.error = str(e)
            self._add_log(f"Run failed: {e}")
            raise
        finally:
            # Don't close browser if we're awaiting approval - we need it for apply
            if self.status not in (AgentStatus.AWAITING_APPROVAL, AgentStatus.APPLYING):
                await self._cleanup_browser()

    async def apply_and_finish(self):
        """Apply to approved jobs and finish the run."""
        if self.status != AgentStatus.AWAITING_APPROVAL:
            raise ValueError(f"Cannot apply: status is {self.status.value}")

        try:
            self.status = AgentStatus.APPLYING
            self._add_log("Applying to approved jobs...")

            if not self._graph or not self._thread:
                raise RuntimeError("Graph or thread not initialized")

            # Get the current state
            snap = await self._graph.aget_state(self._thread)
            values = snap.values

            # Update the state: set is_match=False for rejected jobs
            approved_ids = {jid for jid, app in self.state.approvals.items() if app.approved is True}

            # Update evaluated_jobs in the state
            evaluated_jobs = values.get("evaluated_jobs", [])
            for ej in evaluated_jobs:
                job_id = ej.get("job", {}).get("job_id", "")
                if job_id in self.state.approvals:
                    ej["evaluation"]["is_match"] = job_id in approved_ids

            # Update state through the graph
            # We need to update the state and then resume
            await self._graph.aupdate_state(
                self._thread,
                {"evaluated_jobs": evaluated_jobs},
            )

            # Resume the graph - it will go to apply with the updated state
            self._add_log("Resuming graph...")
            await self._graph.ainvoke(None, self._thread)

            # Get final state
            final_snap = await self._graph.aget_state(self._thread)
            final_values = final_snap.values
            self.state.applied_jobs = final_values.get("applied_jobs", [])
            self.state.errors = final_values.get("errors", [])
            self.state.summary = final_values.get("summary", "")

            self.status = AgentStatus.DONE
            self.state.end_time = datetime.now()
            self._add_log(f"Run completed. Applied to {len(self.state.applied_jobs)} jobs.")

        except Exception as e:
            self.error = str(e)
            self._add_log(f"Apply failed: {e}")
            raise
        finally:
            await self._cleanup_browser()

    async def _apply_and_finish_internal(self, thread):
        """Internal method to apply when there are no approvals needed."""
        try:
            # No approvals, just resume the graph
            self._add_log("Resuming graph (no approvals)...")
            await self._graph.ainvoke(None, thread)
            snap = await self._graph.aget_state(thread)
            values = snap.values
            self.state.applied_jobs = values.get("applied_jobs", [])
            self.state.errors = values.get("errors", [])
            self.state.summary = values.get("summary", "")
            self.status = AgentStatus.DONE
            self.state.end_time = datetime.now()
            self._add_log("Run completed.")
        except Exception as e:
            self.error = str(e)
            raise
        finally:
            await self._cleanup_browser()

    async def _cleanup_browser(self):
        """Clean up Playwright resources."""
        try:
            if self._page:
                await self._page.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            self._add_log(f"Browser cleanup error: {e}")
        self._page = None
        self._browser = None
        self._playwright = None

    def _reset_state(self):
        """Reset the state for a new run."""
        self.state = AgentRunState()
        self.state.thread_id = f"web-run-{int(time.time())}"
        self._thread = None
        self._graph = None
        self._nodes = None
        self._add_log("State reset")

# Global runner instance
_runner: Optional[AgentWebRunner] = None

def get_agent_runner() -> AgentWebRunner:
    """Get or create the global agent runner."""
    global _runner
    if _runner is None:
        _runner = AgentWebRunner()
    return _runner
