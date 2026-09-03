from pydantic import BaseModel, Field


class ConsentRequest(BaseModel):
    policy_version: str = Field(default="0.0.1", min_length=1, max_length=20)
    scope: str = Field(default="health_data_collection", max_length=200)


class ConsentResponse(BaseModel):
    policy_version: str
    consented: bool
    disclaimer_text: str


class PolicyResponse(BaseModel):
    policy_version: str
    disclaimer_text: str