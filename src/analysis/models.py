from pydantic import BaseModel, ConfigDict, Field


class Technology(BaseModel):
    name: str = Field(min_length=1)
    usage: str = Field(min_length=1)
    source_files: list[str] = Field(min_length=1)


class ProjectArea(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    optimization_topics: list[str] = Field(min_length=1)
    source_files: list[str] = Field(min_length=1)


class GeneratedQuestion(BaseModel):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    context: str = Field(min_length=1)
    source_files: list[str] = Field(min_length=1)


class CodebaseAnalysis(BaseModel):
    summary: str = Field(min_length=1)
    technologies: list[Technology] = Field(min_length=1)
    project_areas: list[ProjectArea] = Field(min_length=1)
    questions: list[GeneratedQuestion] = Field(min_length=3, max_length=3)


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    repo_url: str = Field(min_length=1, max_length=300)
    role: str = Field(default="Software Engineer", min_length=1, max_length=200)
    subdir: str = Field(default="", max_length=300)
