"""WebFetch 工具 — HTTP 请求"""
import httpx
from pydantic import BaseModel, Field

from .base import Tool, ToolResult, ToolUseContext


class WebFetchInput(BaseModel):
    url: str = Field(description="URL to fetch content from")
    prompt: str = Field(default="", description="Prompt to run on the fetched content")


class WebFetchTool(Tool):
    def __init__(self):
        super().__init__(
            name="WebFetch",
            description="""Fetches a URL and returns the content.
HTTP is upgraded to HTTPS.
Use for: reading documentation, API responses, web content.""",
            input_schema=WebFetchInput,
        )

    async def call(self, input_data: WebFetchInput, context: ToolUseContext) -> ToolResult:
        url = input_data.url
        if url.startswith("http://"):
            url = "https://" + url[7:]

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "MiniClaudeCode/1.0"})
                resp.raise_for_status()

                content = resp.text[:50000]
                return ToolResult(
                    output=content,
                    metadata={"status_code": resp.status_code, "url": str(resp.url)},
                )
        except Exception as e:
            return ToolResult(output=f"Error fetching URL: {e}", is_error=True)
