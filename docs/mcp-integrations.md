# MCP integrations reference

What this repository's MCP servers can rely on from the Python MCP SDK, the MCP specification
and Claude Code, as researched on 2026-11-25 for the `python-documentation` server (issue #5).
Every claim cites its source. Versions matter: re-check a claim when `uv.lock` moves `mcp` or
Claude Code changes major behaviour.

## Versions this page describes

| Component | Version | Source |
| --- | --- | --- |
| `mcp` (Python SDK) | 2.3.0, latest release on 2026-10-02 | `uv.lock`, [PyPI history](https://pypi.org/project/mcp/#history) |
| MCP protocol | revisions 2024-11-05 to 2026-07-28 | `mcp_types/version.py` in the installed SDK |
| `httpx2` | 2.16.2 | `uv.lock` |
| Claude Code | 2.1.304 or later for MCP tasks | [MCP docs](https://code.claude.com/docs/en/mcp.md) |

## The Python SDK server surface (mcp 2.3.0)

- Servers are built with `mcp.server.mcpserver.MCPServer`, which has `tool`, `resource` (and
  resource templates), `prompt` and `completion` decorators, plus `add_tool`
  (`mcp/server/mcpserver/server.py`).
- A tool that takes a `Context` can call `report_progress`, `elicit` (form mode),
  `elicit_url` (URL mode) and `log` (`mcp/server/mcpserver/context.py`).
- **Confirmed (building `python-docs-mcp`):** a tool gets its request `Context` only as a
  parameter annotated `Context` (`find_context_parameter`,
  `mcp/server/mcpserver/utilities/context_injection.py:13`; `tools/base.py:88-89`). There is no
  context variable to read it from, and the parameter is left out of the input schema. Under
  ruff `max-args = 3` this cost a `PLR0913` noqa on each docs tool
  (`packages/docs/src/python_agent_tools_docs/server.py:97` and `:115`).
- **Confirmed:** `Context.report_progress(progress, total=None, message=None)`
  (`mcp/server/mcpserver/context.py:120`) is a no-op when the caller sent no progress token
  (`report_progress` docstring, `mcp/server/session.py:429`). A client opts in by passing
  `progress_callback` to `Client.call_tool` (`mcp/client/client.py:761`); see
  `tests/docs/server/e2e/test_progress.py`.
- **Confirmed:** `MCPServer.resource(uri)` registers a resource template when the URI holds
  `{params}` and a static resource otherwise (`mcp/server/mcpserver/server.py:788`, docstring).
  Its `security` argument sets the path-safety policy for extracted template parameters and
  defaults to the server's `resource_security`. `MCPServer.completion()`
  (`server.py:739`) registers the one `completion/complete` handler, called with
  `(ref, argument, context)`. See `tests/docs/server/e2e/test_resources.py`.
- **Confirmed:** `ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True)`
  (`READ_ONLY_REMOTE`, `packages/docs/src/python_agent_tools_docs/server.py:44`) serializes as
  `readOnlyHint`, `idempotentHint` and `openWorldHint`. Checked on 2026-11-25 with
  `ToolAnnotations(...).model_dump(by_alias=True, exclude_none=True)`, which printed
  `{'readOnlyHint': True, 'idempotentHint': True, 'openWorldHint': True}`.
- A tool's `outputSchema` is built from its return annotation through a Pydantic
  `TypeAdapter`. Accepted: `BaseModel`, `TypedDict`, primitives (wrapped as
  `{"result": ...}`), `dict[str, X]`, and other annotated classes such as dataclasses.
  **msgspec is not supported** (`mcp/server/mcpserver/utilities/func_metadata.py`). This
  repository therefore uses Pydantic models at the MCP edge only, with msgspec and dataclasses
  inside.
- Registering a tool with `structured_output=False` returns plain text with no schema.
- Extensions are passed once at construction, `MCPServer("name", extensions=[...])`, and
  cannot be added later. A server extension subclasses `Extension` and may contribute
  capability settings, tools, resources, new request methods, and a `tools/call` interceptor
  (`mcp/server/extension.py`,
  [SDK extensions docs](https://py.sdk.modelcontextprotocol.io/advanced/extensions/#using-an-extension)).
- `mcp` 2.3.0 depends on `httpx2>=2.10.0`, so every member that depends on `mcp` already has
  `httpx2` installed. Do not add `httpx`.

## Structured output

The 2026-07-28 specification says a tool returning `structuredContent` SHOULD also return the
serialized JSON in a text content block for backwards compatibility. With an `outputSchema`,
servers MUST return conforming results and clients SHOULD validate them
([spec, tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools#structured-content)).
Claude Code's documentation does not say which of the two it shows the model, so return both.

## What Claude Code does with a server

### Output size

- A warning appears when one tool's output exceeds 10,000 tokens.
- `MAX_MCP_OUTPUT_TOKENS` defaults to 25,000 and applies to tools that declare no limit.
- Text results over 50,000 characters are saved to a file, and the conversation gets the path.
- A tool can raise its own limit with `_meta["anthropic/maxResultSizeChars"]` in its
  `tools/list` entry, up to 500,000 characters.
- Error results over about 11,000 characters keep only the first and last 5,000.

Source: [MCP output limits and warnings](https://code.claude.com/docs/en/mcp.md#mcp-output-limits-and-warnings).
Design tools to page their output well under 10,000 tokens.

### Session start and descriptions

Only tool names and server instructions load at session start (tool search). Server instructions
and tool descriptions are cut at 4,096 characters, adjustable with
`CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH`
([tool search for MCP server authors](https://code.claude.com/docs/en/mcp.md#tool-search-for-mcp-server-authors)).
Put the routing advice an agent needs in the instructions string and keep it short.

### Tool annotations

- `readOnlyHint: true` lets Claude Code run the call in parallel with other read-only calls.
- `idempotentHint: true` marks the call safe to repeat on a new connection.
- `_meta["anthropic/requiresUserInteraction"]: true` forces a permission prompt on every call,
  even in bypass modes.
- `openWorldHint` and `title` are not mentioned in the Claude Code docs.

Source: [mark tools that are safe to call twice](https://code.claude.com/docs/en/mcp.md#mark-tools-that-are-safe-to-call-twice).

### Resources, prompts and other capabilities

| Capability | Claude Code behaviour | Source |
| --- | --- | --- |
| Resources | @-mentionable as `@server:scheme://path`, listed in @ autocomplete, readable through built-in tools; plain text under `claude -p` | [reference MCP resources](https://code.claude.com/docs/en/mcp.md#reference-mcp-resources) |
| Prompts | Exposed as `/server:prompt` slash commands (also `/mcp__server__prompt`) | [execute MCP prompts](https://code.claude.com/docs/en/mcp.md#execute-mcp-prompts) |
| Elicitation | Form and URL modes; URL mode caps the URL near 8,000 characters | [respond to MCP elicitation requests](https://code.claude.com/docs/en/mcp.md#respond-to-mcp-elicitation-requests) |
| Progress | Resets the idle timeout, not the wall-clock limit | [time limits on MCP tool calls](https://code.claude.com/docs/en/mcp.md) |
| `list_changed` | Refetches tools, prompts or resources while connected | [dynamic tool updates](https://code.claude.com/docs/en/mcp.md) |
| Roots | Answers `roots/list` with the launch and extra working directories | [add a local stdio server](https://code.claude.com/docs/en/mcp.md) |
| Channels | `claude/channel` capability, opted in with `--channels`, bindable in the plugin manifest | [push messages with channels](https://code.claude.com/docs/en/mcp.md) |
| Sampling | Not documented | [MCP docs](https://code.claude.com/docs/en/mcp.md) |

## MCP tasks

- Tasks are an extension, `io.modelcontextprotocol/tasks` (SEP-2663): a tool returns a
  `CreateTaskResult`, and the client calls `tasks/get`, `tasks/update` and `tasks/cancel`.
  Statuses are `working`, `input_required`, `completed`, `failed` and `cancelled`
  ([spec, tasks](https://modelcontextprotocol.io/specification/latest/basic/utilities/tasks)).
- Claude Code runs tasks for stdio, HTTP and claude.ai connector servers on protocol revision
  2026-07-28, from Claude Code 2.1.304
  ([MCP tasks that run on the server](https://code.claude.com/docs/en/mcp.md#mcp-tasks-that-run-on-the-server)).
  Its CHANGELOG through 2.1.332 shows active fixes to background tasks and elicitation.
- **The Python SDK does not implement tasks yet.** `mcp` 2.3.0 negotiates 2026-07-28 and ships
  the task wire types in `mcp_types`, but no server runtime. The v2.2.0 release notes list the
  tasks extension under known gaps, and
  [python-sdk PR #3005](https://github.com/modelcontextprotocol/python-sdk/pull/3005) is still
  open. `modelcontextprotocol/ext-tasks` ships only a TypeScript package.
- Until #3005 merges, a server needing tasks must hand-write an `Extension`. Check that pull
  request first.

## Plugin wiring

- `mcpServers` in `plugin.json` accepts a path to a `.json` file (which may hold several
  servers), an `.mcpb` or `.dxt` bundle, an inline map, or an array of these
  ([plugins reference, mcpServers](https://code.claude.com/docs/en/plugins-reference.md#mcpservers)).
- **Confirmed:** `mcpServers` as an array of two `.json` paths is accepted.
  `.claude-plugin/plugin.json` holds
  `["./mcp-servers/agent-tools-mcp.json","./mcp-servers/python-docs-mcp.json"]`, and
  `claude plugin validate --strict .` on 2026-11-25 printed both servers (`agent-tools-mcp` and
  `python-docs-mcp`) and "✔ Validation passed", as reported by the build session. Its
  directory-profile checks (`README_TRIVIAL`, `ICON_MISSING`) and the "Hosts not declared: list
  what these parts reach under network.hosts" note do not change the verdict.
- **Sandbox:** inside the Claude Code Bash sandbox `.mcp.json` appears as a character device and
  `uv.lock` is read-only, so `claude plugin validate --strict` and `make pre-commit` fail there
  and pass outside it (2026-11-25, as reported by the build session).
- `${CLAUDE_PLUGIN_ROOT}` resolves in a stdio server's `command`, `args` and `env`.
  `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA` and `CLAUDE_PROJECT_DIR` are exported to the
  process, and `${user_config.KEY}` substitutes saved values. Use `CLAUDE_PLUGIN_DATA` for
  state that must survive sessions, and `CLAUDE_PROJECT_DIR` to read the user's project.
- This repository launches each server with
  `uv run --locked --no-dev --package <member> <script>`, with `UV_PROJECT` set to
  `${CLAUDE_PLUGIN_ROOT}` and `UV_PROJECT_ENVIRONMENT` to `${CLAUDE_PLUGIN_ROOT}/.venv`
  (`mcp-servers/agent-tools-mcp.json`).

## httpx2

`httpx2` is Pydantic's continuation of `httpx`, forked from 0.28.1: the import becomes
`httpx2` and `httpcore` becomes `httpcore2`
([changelog 2.0.0b1](https://github.com/pydantic/httpx2/blob/main/src/httpx2/CHANGELOG.md)).
In 2.16.2, `AsyncClient` takes `follow_redirects` (default `False`), the default timeout is
5 seconds for connect, read, write and pool, `MockTransport` is exported for tests, and
`AsyncHTTPTransport` takes `retries` (default 0) (`httpx2/_client.py`, `httpx2/_config.py`).
**Contradicted:** the default request header is `Accept-Encoding: gzip, deflate, zstd`, not
`gzip, deflate, br`. It is built from the decoders installed (`ACCEPT_ENCODING`,
`httpx2/_client.py:108`, used at `:291`), and `uv run python` on 2026-11-25 printed
`gzip, deflate, zstd`. `aiter_bytes` yields decoded bytes (`httpx2/_models.py:993-996`), so byte
progress against `Content-Length` is exact only for an uncompressed body.
`docs.python.org/3.13/objects.inv` answered on 2026-11-25 with `content-type: application/octet-stream`, `content-length: 151561` and no `Content-Encoding`, so its progress
is exact today.

Other changes from httpx: truststore replaces certifi, `Headers.get` returns `str | None`, and
HTTP/2 needs the `http2` extra.

## Not yet checked

- Annotation defaults (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`)
  in the 2026-07-28 [schema](https://modelcontextprotocol.io/specification/2026-07-28/schema.md).
- That @-mentioning the resource template in a live Claude Code session offers version and
  symbol completions. The e2e tests prove the server answers `completion/complete`, not that
  Claude Code asks.
- Claude Code CHANGELOG entries older than 2.1.323 about structured output, sampling,
  `maxResultSizeChars`, resource templates or completions.
