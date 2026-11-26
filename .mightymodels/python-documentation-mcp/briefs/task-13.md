## ASKED
objective: Serve each symbol's documentation section as the MCP resource template python-docs://{version}/{symbol}, with argument completions for version and symbol, so a Claude Code user can @-mention docs without a tool call.
acceptance:
  - Reading python-docs://{version}/{symbol} returns the same section text read_python_docs returns for that symbol and version (the whole section, not one page).
  - Version completions list every version in the settings window (completion_floor_version through completion_ceiling_version), filtered by the typed prefix, with the project's requires-python floor first when one resolves.
  - Symbol completions come only from an inventory already in memory or in the disk store for the version given in the completion context; with none loaded they return no values and the docs site receives no request.
verification: uv run pytest -q tests/docs; uv run ruff check packages/docs/src/python_agent_tools_docs tests/docs; uv run ruff format --check packages/docs/src/python_agent_tools_docs tests/docs; uv run ty check --config-file ty.toml; wc -l on every owned source file (each 300 or fewer)
files-in-scope: [packages/docs/src/python_agent_tools_docs/completions.py, packages/docs/src/python_agent_tools_docs/server.py, packages/docs/src/python_agent_tools_docs/services.py, packages/docs/src/python_agent_tools_docs/store.py, tests/docs/server/e2e/test_resources.py]
interface: mcp 2.3.0 MCPServer.resource(uri, *, name, title, description, mime_type, ...) registers a template when the URI has {params} (.venv/lib/python3.14/site-packages/mcp/server/mcpserver/server.py:788); its security argument applies the server's path-safety policy to extracted parameters, so check a dotted symbol such as os.path.join survives it. MCPServer.completion() (server.py:739) registers the single completion/complete handler, called as func(ref, argument, context) and returning Completion or None; ref is a PromptReference or ResourceTemplateReference, context carries previously resolved arguments (the version, for symbol completions). The types live under mcp.types. Client side for the e2e test: the in-memory Client used in tests/docs/server/e2e/test_tools.py (read_resource and complete). Settings carry completion_floor_version and completion_ceiling_version (settings.py:73-74); project.resolve_floor(environment) returns the floor PythonVersion or a VersionRequiredError (never raises).
reuse-or-delete: Read the section through the existing service path (DocumentationService.catalog then section, as read_python_docs.run does); do not duplicate rendering. Symbol completions need a non-fetching lookup: add a peek on CachedLoader (store.py, returns the cached value or None, never starts a fill) and a service method that returns the catalog from memory, or loads it only when the disk store already holds the version, else None. Known finding from T11 (FC-5): DiskInventoryStore.contains (disk_cache.py:117) reads and may unlink on the calling thread, so call it through anyio.to_thread.run_sync. Cap the completion values at MCP's 100-value limit and set has_more when cut. The behavior handed to the server is a class with verb methods (python.md), not closures; build_server(service, environment) at server.py:125 wires tools today. The fourth plan criterion (the user confirms @-mention completions in a live Claude Code session) is checked by the primary with the user after the plugin wiring tasks, not by this task. Delete nothing.
engineer-tier: sonnet
uses: [.claude/rules/python.md, .claude/rules/testing.md]
toolchain:
  - TC-17 [seen] Makefile:17: `uv run ty check --config-file ty.toml`; the plan's bare `uv run ty check` is declared nowhere, so the config path is the repository's form
  - TC-20 [seen] ruff.toml:113-134: banned APIs `__future__.annotations`, `functools.partial`, `functools.cached_property`, `asyncio.gather` (use TaskGroup), `importlib.import_module`, `sys.path`, `sys.modules`, `abc.ABC`, `sys.exit`, `os.exec*`; no `httpx` ban
  - TC-21 [seen] ruff.toml:140-151: `max-complexity = 8`, `max-args = 3`, `max-positional-args = 3`, `max-returns = 6`, `max-branches = 8`, `max-statements = 25`, `max-nested-blocks = 3`, `max-statements-in-try = 3`
  - TC-22 [seen] ruff.toml:73-80: tests are exempt from S101, PLR2004, PLR0913, PLR0917, FBT001 and TID251 only; ruff.toml:156 `quote-style = "single"`
  - TC-23 [seen] .claude/rules/python.md:22,251,209,137-138: no em dashes anywhere (docs and strings too), no `else` or `elif` blocks, never `while True`, no hand-written `__init__` except on exceptions, no `__post_init__`
  - TC-25 [seen] pytest.toml:2-3,23: `strict = true`, `strict_markers = true`, `filterwarnings = ["error"]`; pytest.toml:13-22: `addopts` add `--cov` and `--import-mode=importlib`
  - TC-29 [seen] .claude/rules/testing.md:20: builders, harnesses and fakes are files under `tests/<pkg>/<concept>/`, and a `conftest.py` holds fixtures only (T5's tests/docs/support/docs_site.py)
  - TC-38 [seen] .claude/settings.json:13-45: PreToolUse hook `pyhooks.py suppressions` on Write|Edit asks approval when a change adds a lint or type suppression; PostToolUse runs `format` after Write|Edit and `diagnose` after Read

## DONE

Added the python-docs://{version}/{symbol} resource template (DocumentationTools.read_section, errors surface as ResourceError), and a DocumentationCompletions class registered through server.completion(). Versions come from the settings window with the project floor first; symbols come from CachedLoader.peek or, via DocumentationService.stored_catalog, the disk store when anyio.to_thread confirms it holds the version, else no values and no request. Values cap at 100 with has_more. DocumentationService now carries the store.

commit: f40ee15

Checks run (all passed):
- uv run pytest -q tests/docs: 242 passed
- uv run ruff check packages/docs/src/python_agent_tools_docs tests/docs: All checks passed!
- uv run ruff format --check ...: 34 files already formatted
- uv run ty check --config-file ty.toml: All checks passed!
- wc -l: completions 103, server 177, services 166, store 105
