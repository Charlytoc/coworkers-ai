from typing import Optional

from ninja import Schema
from pydantic import Field
from typing_extensions import Literal


class ExchangeMessage(Schema):
    id: Optional[int] = Field(default=None, description="Message ID")
    type: Literal["text", "file"] = "text"
    role: Literal["user", "assistant", "tool_call", "tool_result"] = "user"
    content: str | dict = Field(default="", description="Content of the message")
    created: Optional[str] = Field(default=None, description="Creation timestamp")

    model_config = {"extra": "ignore"}
