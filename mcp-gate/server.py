from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import AcceptedElicitation
from mcp.types import (
    ClientCapabilities,
    ElicitationCapability,
    ElicitRequest,
    ElicitRequestFormParams,
    InputRequiredResult,
)
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

mcp = FastMCP("mcp-gate")

QUESTION = "What is 2 + 2?"
ANSWER_KEY = "answer"
SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string", "title": "Answer"}},
    "required": ["value"],
}


def _answer_text(action: str, content: dict | None) -> str:
    if action == "accept" and content:
        return str(content.get("value", ""))
    return f"User did not answer (action: {action})."


@mcp.tool
async def ask_test(ctx: Context) -> str | InputRequiredResult:
    """Ask the user "What is 2 + 2?" via elicitation and return what they typed."""
    rc = ctx.request_context
    modern = rc is not None and rc.protocol_version in MODERN_PROTOCOL_VERSIONS

    if modern:
        # 2026-07-28 era: no server-initiated requests. Return input_requests,
        # the client prompts the user and re-calls the tool with input_responses.
        responses = ctx.input_responses
        if responses and ANSWER_KEY in responses:
            resp = responses[ANSWER_KEY]
            return _answer_text(resp.action, resp.content)
        return InputRequiredResult(
            input_requests={
                ANSWER_KEY: ElicitRequest(
                    params=ElicitRequestFormParams(
                        message=QUESTION, requested_schema=SCHEMA
                    )
                )
            }
        )

    # Handshake era: classic server-initiated elicitation.
    supported = ctx.session.check_client_capability(
        ClientCapabilities(elicitation=ElicitationCapability())
    )
    if not supported:
        raise ToolError(
            "This MCP client does not support elicitation, so ask_test cannot "
            "prompt the user. Use a client that advertises the elicitation capability."
        )
    result = await ctx.elicit(QUESTION, response_type=str)
    if isinstance(result, AcceptedElicitation):
        return result.data
    return f"User did not answer (action: {result.action})."


if __name__ == "__main__":
    mcp.run()
