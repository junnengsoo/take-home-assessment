from typing import Literal

from pydantic import BaseModel, Field


class LeadStatusMutation(BaseModel):
    status: Literal["PENDING", "REACHED_OUT"]
    version: int = Field(ge=1)
