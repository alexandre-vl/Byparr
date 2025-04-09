from __future__ import annotations

import time
from http import HTTPStatus
from typing import Any

from pydantic import BaseModel, Field
from pydantic.alias_generators import to_camel

from src import consts


class LinkRequest(BaseModel):
    cmd: str = Field(
        default="request.get",
        description="Type of request, currently only supports GET requests. This string is purely for compatibility with FlareSolverr.",
    )
    url: str = Field(pattern=r"^https?://", default="https://")
    max_timeout: int = Field(default=60)


class Solution(BaseModel):
    url: str
    status: int
    cookies: list
    userAgent: str  # noqa: N815 # Ignore to preserve compatibility
    headers: dict[str, Any]
    response: str

    @classmethod
    def invalid(cls, url: str):
        """
        Return an empty Solution with default values.

        Useful for returning an error response.
        """
        return cls(
            url=url,
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
            cookies=[],
            userAgent="",
            headers={},
            response="",
        )


class LinkResponse(BaseModel):
    model_config = {"alias_generator": to_camel, "populate_by_name": True}
    status: str = "ok"
    message: str
    solution: Solution
    start_timestamp: int
    end_timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))
    version: str = consts.VERSION

    @classmethod
    def invalid(cls, url: str):
        """
        Return an invalid LinkResponse with default error values.

        This method is used to generate a response indicating an invalid request.
        """
        return cls(
            status="error",
            message="Invalid request",
            solution=Solution.invalid(url),
            start_timestamp=int(time.time() * 1000),
        )


class ImageDownloadRequest(BaseModel):
    url: str = Field(pattern=r"^https?://", description="URL of the page containing the image")
    image_selector: str = Field(description="CSS selector to identify the image element")
    max_timeout: int = Field(default=60)
