import base64
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableLambda

import agent_graph
from agent_graph import AgentNodes, build_summary, route_after_evaluation
from gmail_otp import extract_otp, wait_for_otp
from llm_evaluator import build_evaluator
from models import EvaluatedJob, Job, JobEvaluation


class OtpExtractionTests(unittest.TestCase):
    def test_extracts_six_digit_code(self):
        self.assertEqual(extract_otp("Your ERP OTP is 482913. Valid 10 minutes."), "482913")

    def test_extracts_four_digit_code(self):
        self.assertEqual(extract_otp("Code: 1234"), "1234")

    def test_returns_none_when_no_code(self):
        self.assertIsNone(extract_otp("No digits here."))


class WaitForOtpTests(unittest.TestCase):
    def _service_with_message(self, body_text: str):
        encoded = base64.urlsafe_b64encode(body_text.encode()).decode()
        service = MagicMock()
        msgs = service.users.return_value.messages.return_value
        msgs.list.return_value.execute.return_value = {"messages": [{"id": "m1"}]}
        msgs.get.return_value.execute.return_value = {
            "id": "m1",
            "snippet": body_text,
            "payload": {"mimeType": "text/plain", "body": {"data": encoded}},
        }
        return service, msgs

    def test_polls_extracts_and_marks_read(self):
        service, msgs = self._service_with_message("OTP: 771204")
        otp = wait_for_otp(service, "erp@univ.edu", since_epoch=0,
                           timeout=5, poll_interval=0.01)
        self.assertEqual(otp, "771204")
        msgs.modify.assert_called_once()  # email marked as read

    def test_times_out_when_no_email(self):
        service = MagicMock()
        service.users.return_value.messages.return_value.list.return_value \
            .execute.return_value = {"messages": []}
        with self.assertRaises(TimeoutError):
            wait_for_otp(service, "erp@univ.edu", 0, timeout=0.2, poll_interval=0.05)


class SchemaTests(unittest.TestCase):
    def test_evaluation_schema_is_exactly_is_match_and_reason(self):
        schema = JobEvaluation.model_json_schema()
        self.assertEqual(set(schema["properties"]), {"is_match", "reason"})
        self.assertEqual(set(schema["required"]), {"is_match", "reason"})


class StubLLM:
    """Mimics a chat model's with_structured_output without any API calls."""
    def __init__(self, result):
        self._result = result

    def with_structured_output(self, schema):
        return RunnableLambda(lambda _: self._result)


class EvaluatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_evaluator_returns_structured_output(self):
        evaluate = build_evaluator(
            "Python, SQL, ML student",
            llm=StubLLM(JobEvaluation(is_match=True, reason="Strong skill overlap.")),
        )
        result = await evaluate(Job(job_id="0", company="Acme", role="SDE",
                                    description="Need Python and SQL."))
        self.assertIsInstance(result, JobEvaluation)
        self.assertTrue(result.is_match)


def _state(**overrides):
    base = {"available_jobs": [], "evaluated_jobs": [], "applied_jobs": [],
            "errors": [], "summary": ""}
    base.update(overrides)
    return base


def _evaluated(company: str, is_match: bool) -> EvaluatedJob:
    return EvaluatedJob(
        job=Job(job_id="0", company=company, role="SDE"),
        evaluation=JobEvaluation(is_match=is_match, reason="test"),
    )


class RoutingTests(unittest.TestCase):
    def test_routes_to_apply_when_match_exists(self):
        state = _state(evaluated_jobs=[_evaluated("Acme", True)])
        self.assertEqual(route_after_evaluation(state), "apply")

    def test_routes_to_notify_when_no_match(self):
        state = _state(evaluated_jobs=[_evaluated("Acme", False)])
        self.assertEqual(route_after_evaluation(state), "notify")


class NodeTests(unittest.IsolatedAsyncioTestCase):
    async def test_evaluate_node_collects_evaluations(self):
        async def fake_evaluate(job):
            return JobEvaluation(is_match=True, reason="fit")

        nodes = AgentNodes(page=None, cfg=None, evaluate_fn=fake_evaluate,
                           otp_provider=None, notify_fn=None)
        jobs = [Job(job_id="0", company="Acme", role="SDE"),
                Job(job_id="1", company="Globex", role="Data Analyst")]
        with patch.object(agent_graph, "read_job_description",
                          new=AsyncMock(return_value="JD text")):
            result = await nodes.evaluate(_state(available_jobs=jobs))
        self.assertEqual(len(result["evaluated_jobs"]), 2)
        self.assertEqual(result["evaluated_jobs"][0].job.description, "JD text")

    async def test_apply_node_only_applies_to_matches(self):
        nodes = AgentNodes(page=None, cfg=None, evaluate_fn=None,
                           otp_provider=None, notify_fn=None)
        state = _state(evaluated_jobs=[_evaluated("Acme", True),
                                       _evaluated("Globex", False)])
        with patch.object(agent_graph, "apply_to_job", new=AsyncMock()) as mock_apply:
            result = await nodes.apply(state)
        self.assertEqual(mock_apply.await_count, 1)
        self.assertEqual(result["applied_jobs"], ["Acme - SDE"])


class SummaryTests(unittest.TestCase):
    def test_summary_includes_counts_and_companies(self):
        state = _state(
            available_jobs=[Job(job_id="0", company="Acme", role="SDE")],
            evaluated_jobs=[_evaluated("Acme", True)],
            applied_jobs=["Acme - SDE"],
        )
        summary = build_summary(state)
        self.assertIn("Jobs found: 1", summary)
        self.assertIn("Acme", summary)
        self.assertIn("Applied (1)", summary)


if __name__ == "__main__":
    unittest.main()