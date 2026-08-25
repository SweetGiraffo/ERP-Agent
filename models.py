from pydantic import BaseModel, Field


class Job(BaseModel):
    job_id: str
    company: str
    role: str
    deadline: str = ""
    description: str = ""


class JobEvaluation(BaseModel):
    """Structured LLM output. Keep exactly these two fields."""
    is_match: bool = Field(
        description="True only if the resume is a strong fit for the job description."
    )
    reason: str = Field(description="One or two sentences explaining the decision.")


class EvaluatedJob(BaseModel):
    job: Job
    evaluation: JobEvaluation