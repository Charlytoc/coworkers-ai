from typing import Optional

from django.utils import timezone
from ninja import Schema
from pydantic import Field
from typing_extensions import Literal


class ExchangeMessage(Schema):
    id: Optional[int] = Field(default=None, description="Message ID")
    type: Literal["text", "file", "tool_call", "tool_result"] = "text"
    role: Literal["user", "assistant"] = "user"
    content: str | dict = Field(default="", description="Content of the message")
    created: Optional[str] = Field(
        default_factory=lambda: timezone.now().isoformat(),
        description="Creation timestamp. Auto-filled to now() unless the caller passes the "
        "original timestamp (e.g. a real Message's created date).",
    )

    model_config = {"extra": "ignore"}

