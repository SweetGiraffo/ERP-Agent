from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from models import Job, JobEvaluation

SYSTEM_PROMPT = """You are a strict career-fit evaluator for a student job seeker.
Compare the resume against the job description.
Set is_match=true ONLY if the candidate meets the core eligibility criteria
(degree, graduation year, required skills) and the role is genuinely relevant.
Otherwise set is_match=false. Always give a brief, honest reason."""


def build_evaluator(resume_text: str, model_name: str = "gpt-4o-mini", llm=None):
    """Returns an async callable: Job -> JobEvaluation.

    `llm` is injectable so tests can substitute a fake model.
    """
    llm = llm or ChatOpenAI(model=model_name, temperature=0)
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human",
         "RESUME:\n{resume}\n\nCOMPANY: {company}\nROLE: {role}\n\n"
         "JOB DESCRIPTION:\n{description}"),
    ])
    chain = prompt | llm.with_structured_output(JobEvaluation)

    async def evaluate(job: Job) -> JobEvaluation:
        return await chain.ainvoke({
            "resume": resume_text,
            "company": job.company,
            "role": job.role,
            "description": job.description or "(no description available)",
        })

    return evaluate