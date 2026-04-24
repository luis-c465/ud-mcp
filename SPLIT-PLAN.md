# Split Implementation Plan for Universal Database MCP Server

This document decomposes `PLAN.md` into granular, mostly single-owner tasks so individual agents can work in parallel with clear boundaries.

## Ground Rules

- **Language/runtime:** Python 3.12+
- **Tooling/package management:** **uv**
- **Framework:** official `mcp` Python SDK with **FastMCP**
- **Architecture:** MCP layer -> service layer -> adapter layer -> driver layer
- **Default safety mode:** **read-only**
- **Target backends:** SQL Server, Snowflake, Databricks
- **Work style:** each agent should own one narrow deliverable with explicit outputs and acceptance criteria

---

## Suggested Delivery Order

These tasks are intentionally small. Some can run in parallel once their dependencies are ready.

### Stage 0: Repo and scaffolding

1. Initialize Python project with `uv`
2. Create package skeleton under `src/db_mcp_server/`
3. Add baseline dependency manifest
4. Add developer docs / README stub

### Stage 1: Shared foundations

5. Define config models
6. Implement config loader
7. Implement secret resolution helpers
8. Define normalized domain models
9. Define shared error model
10. Define logging + redaction utilities

### Stage 2: Safety and policy core

11. Implement SQL parsing/classification with `sqlglot`
12. Implement permission/policy engine
13. Implement query limit enforcement helpers
14. Implement request validation service

### Stage 3: Service layer

15. Implement connection registry
16. Implement result formatter
17. Implement audit service
18. Implement metadata service
19. Implement query service

### Stage 4: Adapter and driver base

20. Define adapter protocol/base classes
21. Implement SQLAlchemy shared adapter helpers
22. Implement SQL Server driver setup
23. Implement Snowflake driver setup
24. Implement Databricks driver setup

### Stage 5: Backend adapters

25. Implement SQL Server adapter
26. Implement Snowflake adapter
27. Implement Databricks adapter
28. Cross-adapter metadata normalization pass

### Stage 6: MCP surface

29. Define MCP request/response schemas
30. Implement MCP tools
31. Implement MCP resources/prompts placeholders
32. Implement server startup wiring
33. Implement CLI entrypoint and transport selection

### Stage 7: Quality and hardening

34. Unit tests for safety logic
35. Unit tests for config and services
36. Adapter contract tests
37. MCP integration smoke tests
38. Audit/logging review
39. Dependency and packaging review

---

## Agent-by-Agent Task Breakdown

## Agent 01 — Project bootstrap with uv

**Goal**
Create the project foundation using `uv`.

**Scope**

- Initialize Python package/project metadata
- Configure Python 3.12+
- Add `src/` layout
- Add baseline dev commands

**Deliverables**

- `pyproject.toml`
- `uv.lock` (when dependencies are resolved)
- `src/db_mcp_server/__init__.py`
- basic README stub

**Implementation notes**

- Use `uv init` style project structure
- Set project name to something like `universal-db-mcp` or `db-mcp-server`
- Keep entry points minimal for now

**Acceptance criteria**

- `uv sync` succeeds
- package imports from `src/db_mcp_server`
- Python version constraint is 3.12+

**Dependencies**

- none

---

## Agent 02 — Directory skeleton

**Goal**
Create the package/module structure from the architecture plan.

**Scope**
Create empty modules/directories for:

- `config/`
- `mcp/`
- `services/`
- `adapters/`
- `drivers/`
- `safety/`
- `models/`
- `util/`

**Deliverables**

- package directories with `__init__.py`
- placeholder files matching the target layout

**Acceptance criteria**

- imports resolve cleanly
- structure matches `PLAN.md`

**Dependencies**

- Agent 01

---

## Agent 03 — Dependency manifest

**Goal**
Encode the day-1 dependencies in the `uv` project config.

**Scope**
Add required runtime dependencies:

- `mcp`
- `sqlalchemy>=2.0`
- `pydantic>=2`
- `sqlglot`
- `tenacity`
- `orjson`
- `pyodbc`
- `snowflake-sqlalchemy`
- `databricks-sql-connector[pyarrow]`
- optionally gate `databricks-sqlalchemy`

Add optional/dev dependencies for testing/linting if desired.

**Deliverables**

- dependency entries in `pyproject.toml`
- documented extras for optional packages

**Acceptance criteria**

- `uv sync` works on supported systems
- optional dependencies are clearly separated if needed

**Dependencies**

- Agent 01

---

## Agent 04 — Configuration models

**Goal**
Define all typed configuration models with Pydantic.

**Scope**
Model:

- server config
- defaults config
- connection config base
- backend-specific connection config
- policy flags such as `read_only` and `allow_full_permissions`

**Deliverables**

- `src/db_mcp_server/config/models.py`

**Key design points**

- Use discriminated unions for connection `type`
- Ensure env-backed secret references are explicit fields
- Keep config names aligned with `PLAN.md`

**Acceptance criteria**

- YAML-shaped data validates cleanly
- invalid backend config gives structured validation errors

**Dependencies**

- Agent 02

---

## Agent 05 — Config loader

**Goal**
Load YAML configuration and convert it into validated models.

**Scope**

- read YAML file
- parse into config models
- provide friendly error messages
- support explicit config path input

**Deliverables**

- `src/db_mcp_server/config/loader.py`

**Acceptance criteria**

- invalid YAML is surfaced clearly
- valid config returns typed config objects

**Dependencies**

- Agent 04

---

## Agent 06 — Secret resolution

**Goal**
Resolve environment-variable-backed secrets safely.

**Scope**

- read env vars referenced by config
- centralize missing-secret errors
- avoid logging secret values
- provide redacted debug representations

**Deliverables**

- `src/db_mcp_server/config/secrets.py`

**Acceptance criteria**

- missing env vars produce stable, non-secret-leaking errors
- secret values never appear in logs or repr output

**Dependencies**

- Agent 04

---

## Agent 07 — Normalized domain models

**Goal**
Define the shared models used across services and adapters.

**Scope**
Model:

- connection descriptors
- schema/table metadata
- table descriptions / columns
- query options
- query results
- explain results
- warnings / truncation info

**Deliverables**

- `src/db_mcp_server/models/connection.py`
- `src/db_mcp_server/models/query.py`
- `src/db_mcp_server/models/result.py`
- `src/db_mcp_server/models/metadata.py`

**Acceptance criteria**

- shared models cover all planned tool outputs
- naming is backend-neutral: `catalog`, `schema`, `name`, `object_type`

**Dependencies**

- Agent 02

---

## Agent 08 — Error model

**Goal**
Create stable internal and MCP-facing error types.

**Scope**
Implement normalized codes:

- `UNKNOWN_CONNECTION`
- `CONNECTION_FAILED`
- `AUTH_FAILED`
- `QUERY_BLOCKED`
- `QUERY_TIMEOUT`
- `QUERY_TOO_LARGE`
- `INVALID_SQL`
- `UNSUPPORTED_OPERATION`
- `BACKEND_ERROR`

**Deliverables**

- `src/db_mcp_server/safety/errors.py`
- shared exception classes / helpers

**Acceptance criteria**

- callers can map raw exceptions into stable codes
- raw driver exceptions are not passed through directly

**Dependencies**

- Agent 02

---

## Agent 09 — Logging and redaction utilities

**Goal**
Implement safe structured logging helpers.

**Scope**

- logging config
- request-id support
- DSN/token/password redaction
- helper for timing/log context

**Deliverables**

- `src/db_mcp_server/util/logging.py`
- `src/db_mcp_server/util/redact.py`
- `src/db_mcp_server/util/timing.py`

**Acceptance criteria**

- logs can include connection name, statement type, elapsed ms
- secret values are consistently redacted

**Dependencies**

- Agent 08

---

## Agent 10 — SQL parsing and classification

**Goal**
Build SQL analysis utilities around `sqlglot`.

**Scope**

- parse SQL
- detect syntax/parse errors
- classify statement type
- detect multi-statement input
- flag DDL/DML/destructive SQL
- identify explain-like statements where possible

**Deliverables**

- `src/db_mcp_server/safety/sql_parser.py`

**Acceptance criteria**

- `SELECT` is recognized as read-only
- write/DDL statements are classified correctly
- semicolon-separated multiple statements are detected

**Dependencies**

- Agent 08

---

## Agent 11 — Policy engine

**Goal**
Enforce readonly/full-permission behavior consistently.

**Scope**
Implement rules for:

- request-level `permission_mode`
- connection-level `allow_full_permissions`
- `read_only` connection behavior
- optional allow/deny policy hooks

**Deliverables**

- `src/db_mcp_server/safety/policies.py`

**Acceptance criteria**

- non-read-only SQL is blocked in readonly mode
- full mode requires both request opt-in and connection opt-in
- policy decisions return machine-readable reasons

**Dependencies**

- Agent 10
- Agent 04

---

## Agent 12 — Limits and truncation helpers

**Goal**
Implement timeout, row limit, and payload size rules.

**Scope**

- bounds checking for request options
- helpers for `max_rows + 1` fetch semantics
- result truncation flags/warnings
- byte/row guardrails

**Deliverables**

- `src/db_mcp_server/safety/limits.py`

**Acceptance criteria**

- oversized requests are rejected or truncated deterministically
- truncation metadata is preserved in results

**Dependencies**

- Agent 07

---

## Agent 13 — Validation service

**Goal**
Provide one place for request validation before execution.

**Scope**
Validate:

- connection exists
- SQL present
- timeout within bounds
- row limit within bounds
- permission mode valid
- schema/table required fields for metadata tools

**Deliverables**

- `src/db_mcp_server/services/validation_service.py`

**Acceptance criteria**

- bad requests fail before hitting adapters
- service returns normalized errors

**Dependencies**

- Agent 05
- Agent 08
- Agent 12

---

## Agent 14 — Connection registry

**Goal**
Centralize configured connections and adapter lookup.

**Scope**

- list configured connections
- fetch connection by name
- instantiate correct adapter per backend type
- cache reusable factories if appropriate

**Deliverables**

- `src/db_mcp_server/services/connection_registry.py`

**Acceptance criteria**

- unknown names raise `UNKNOWN_CONNECTION`
- backend type maps cleanly to adapter implementation

**Dependencies**

- Agent 04
- Agent 06
- Agent 08

---

## Agent 15 — Result formatter

**Goal**
Normalize backend results into stable shapes.

**Scope**

- column metadata formatting
- rows as arrays
- row count
- elapsed time
- truncated flag
- warnings
- backend metadata such as query id

**Deliverables**

- `src/db_mcp_server/services/result_formatter.py`

**Acceptance criteria**

- result shape is identical regardless of backend
- output is suitable for MCP tool responses

**Dependencies**

- Agent 07

---

## Agent 16 — Audit service

**Goal**
Log execution decisions and outcomes safely.

**Scope**
Record:

- request id
- tool name
- connection name
- statement fingerprint
- statement type
- permission mode
- policy decision
- success/failure
- elapsed ms
- row count
- truncation

**Deliverables**

- `src/db_mcp_server/services/audit_service.py`

**Acceptance criteria**

- logs never contain raw secrets
- audit events are structured and consistent

**Dependencies**

- Agent 09
- Agent 10

---

## Agent 17 — Metadata service

**Goal**
Implement orchestration for metadata tool operations.

**Scope**
Service methods for:

- `list_schemas`
- `list_tables`
- `describe_table`

**Deliverables**

- `src/db_mcp_server/services/metadata_service.py`

**Acceptance criteria**

- service delegates to adapters only after validation
- outputs use normalized metadata models

**Dependencies**

- Agent 13
- Agent 14
- Agent 15

---

## Agent 18 — Query service

**Goal**
Implement the full query execution pipeline.

**Scope**
Pipeline should cover:

1. validation
2. connection resolution
3. SQL parse/classification
4. policy enforcement
5. execution
6. result normalization
7. audit logging

Include both:

- `run_query`
- `explain_query`

**Deliverables**

- `src/db_mcp_server/services/query_service.py`

**Acceptance criteria**

- readonly behavior is enforced end-to-end
- full mode is blocked unless both gates are satisfied
- all failures map to normalized errors

**Dependencies**

- Agent 10
- Agent 11
- Agent 12
- Agent 13
- Agent 14
- Agent 15
- Agent 16

---

## Agent 19 — Adapter interface and base protocol

**Goal**
Define the formal adapter contract.

**Scope**
Create `DatabaseAdapter` protocol/base with methods for:

- `test_connection`
- `list_schemas`
- `list_tables`
- `describe_table`
- `run_query`
- `explain_query`

**Deliverables**

- `src/db_mcp_server/adapters/base.py`

**Acceptance criteria**

- all backend adapters can implement the same contract
- type signatures match normalized models

**Dependencies**

- Agent 07

---

## Agent 20 — Shared SQLAlchemy adapter helpers

**Goal**
Factor common SQLAlchemy behavior into reusable utilities.

**Scope**

- engine creation helpers
- reflection helpers
- row/column extraction helpers
- common execution wrapper

**Deliverables**

- `src/db_mcp_server/adapters/sqlalchemy_base.py`

**Acceptance criteria**

- SQL Server and Snowflake adapters can reuse the shared code
- backend-specific quirks remain overridable

**Dependencies**

- Agent 19

---

## Agent 21 — SQL Server driver wiring

**Goal**
Implement SQL Server engine construction details.

**Scope**

- build `mssql+pyodbc` connection path
- support DSN/env-based configuration
- pool defaults with pre-ping
- optional future placeholder for `mssql-python`

**Deliverables**

- `src/db_mcp_server/drivers/sqlserver_engine.py`

**Acceptance criteria**

- engine config is built from validated config + env secrets
- secret material is redacted in debug output

**Dependencies**

- Agent 06
- Agent 20

---

## Agent 22 — Snowflake driver wiring

**Goal**
Implement Snowflake engine construction details.

**Scope**

- build SQLAlchemy engine via `snowflake-sqlalchemy`
- map warehouse/database/schema/role config
- handle auth/env inputs cleanly

**Deliverables**

- `src/db_mcp_server/drivers/snowflake_engine.py`

**Acceptance criteria**

- engine can be constructed from config consistently
- backend-specific auth fields are encapsulated here

**Dependencies**

- Agent 06
- Agent 20

---

## Agent 23 — Databricks driver wiring

**Goal**
Implement Databricks client setup.

**Scope**

- configure `databricks-sql-connector`
- resolve hostname/http path/token
- establish simpler per-request client pattern first

**Deliverables**

- `src/db_mcp_server/drivers/databricks_client.py`

**Acceptance criteria**

- connection/client creation is isolated from higher layers
- query execution hooks can return normalized raw results

**Dependencies**

- Agent 06
- Agent 19

---

## Agent 24 — SQL Server adapter

**Goal**
Implement the SQL Server backend adapter.

**Scope**

- test connection
- list schemas
- list tables/views
- describe table
- run query
- explain query if supported reasonably

**Deliverables**

- `src/db_mcp_server/adapters/sqlserver.py`

**Acceptance criteria**

- output conforms to shared models
- SQL Server-specific metadata maps to `catalog/schema/name/object_type`

**Dependencies**

- Agent 19
- Agent 20
- Agent 21

---

## Agent 25 — Snowflake adapter

**Goal**
Implement the Snowflake backend adapter.

**Scope**
Same methods as SQL Server adapter, using Snowflake specifics.

**Deliverables**

- `src/db_mcp_server/adapters/snowflake.py`

**Acceptance criteria**

- output conforms to shared models
- Snowflake database/schema mapping is normalized correctly

**Dependencies**

- Agent 19
- Agent 20
- Agent 22

---

## Agent 26 — Databricks adapter

**Goal**
Implement the Databricks backend adapter.

**Scope**

- metadata enumeration
  n- query execution via native connector
- explain support if available/practical
- catalog/schema normalization

**Deliverables**

- `src/db_mcp_server/adapters/databricks.py`

**Acceptance criteria**

- Databricks results fit the same shared contract as other adapters
- catalog/schema semantics are normalized

**Dependencies**

- Agent 19
- Agent 23

---

## Agent 27 — Cross-adapter normalization review

**Goal**
Verify the three adapters behave consistently.

**Scope**

- compare metadata field shapes
- compare query result structures
- compare connection test outputs
- identify backend-specific leaks into shared models

**Deliverables**

- normalization fixes across adapters/services
- short compatibility report

**Acceptance criteria**

- callers do not need backend-specific branching for normal tool outputs

**Dependencies**

- Agent 24
- Agent 25
- Agent 26
- Agent 15

---

## Agent 28 — MCP schemas

**Goal**
Define request/response models for the MCP tool surface.

**Scope**
Create schemas for:

- `list_connections`
- `test_connection`
- `list_schemas`
- `list_tables`
- `describe_table`
- `run_query`
- `explain_query`

**Deliverables**

- `src/db_mcp_server/mcp/schemas.py`

**Acceptance criteria**

- schemas align with normalized service layer models
- tool inputs are explicit and typed

**Dependencies**

- Agent 07
- Agent 18

---

## Agent 29 — MCP tools implementation

**Goal**
Expose the stable tool surface through FastMCP.

**Scope**
Register tools:

- `list_connections`
- `test_connection`
- `list_schemas`
- `list_tables`
- `describe_table`
- `run_query`
- `explain_query`

**Deliverables**

- `src/db_mcp_server/mcp/tools.py`

**Acceptance criteria**

- each tool delegates to services, not directly to adapters
- errors are returned in stable, client-safe form

**Dependencies**

- Agent 17
- Agent 18
- Agent 28

---

## Agent 30 — MCP resources and prompts placeholders

**Goal**
Add the optional MCP resources/prompts layer scaffolding.

**Scope**

- create minimal resources module
- create minimal prompts module
- keep phase-1 behavior simple

**Deliverables**

- `src/db_mcp_server/mcp/resources.py`
- `src/db_mcp_server/mcp/prompts.py`

**Acceptance criteria**

- modules exist and are wired cleanly without blocking MVP

**Dependencies**

- Agent 02

---

## Agent 31 — Server assembly

**Goal**
Wire the FastMCP server and all services together.

**Scope**

- instantiate config
- build registry/services
- register tools/resources/prompts
- return configured FastMCP app/server

**Deliverables**

- `src/db_mcp_server/server.py`

**Acceptance criteria**

- one function can build the server from config
- application boot path is clear and testable

**Dependencies**

- Agent 29
- Agent 30
- Agent 14
- Agent 17
- Agent 18

---

## Agent 32 — CLI entrypoint and transport options

**Goal**
Provide executable startup behavior.

**Scope**

- CLI / `main.py`
- support `--transport stdio`
- support `--transport streamable-http --host --port`
- config path flag

**Deliverables**

- `src/db_mcp_server/main.py`

**Acceptance criteria**

- app can start in stdio mode for development
- HTTP startup path is scaffolded for phase 2

**Dependencies**

- Agent 31

---

## Agent 33 — Unit tests for safety logic

**Goal**
Test the most failure-prone safety behaviors early.

**Scope**
Test:

- SQL classification
- multi-statement detection
- readonly blocking
- full-mode gating
- limit validation

**Deliverables**

- safety-focused test suite

**Acceptance criteria**

- dangerous/default-blocked SQL cases are covered
- permission matrix is explicit in tests

**Dependencies**

- Agent 10
- Agent 11
- Agent 12

---

## Agent 34 — Unit tests for config and services

**Goal**
Validate config loading and core orchestration logic.

**Scope**
Test:

- YAML loading
- secret resolution failures
- connection lookup
- result formatting
- query service orchestration with mocked adapters

**Deliverables**

- config/service unit tests

**Acceptance criteria**

- service layer can be tested without live databases

**Dependencies**

- Agent 05
- Agent 06
- Agent 14
- Agent 15
- Agent 18

---

## Agent 35 — Adapter contract tests

**Goal**
Verify all adapters honor the same interface and output shapes.

**Scope**

- define shared adapter test expectations
- use fixtures/mocks where live DBs are unavailable
- assert normalized field names and result structures

**Deliverables**

- adapter contract test suite

**Acceptance criteria**

- every adapter passes the same behavioral contract tests

**Dependencies**

- Agent 24
- Agent 25
- Agent 26
- Agent 27

---

## Agent 36 — MCP integration smoke tests

**Goal**
Ensure the tool surface is wired correctly end-to-end.

**Scope**

- boot server in test mode
- invoke key tools with mocked services/adapters
- assert structured responses and error handling

**Deliverables**

- MCP integration/smoke tests

**Acceptance criteria**

- basic tool registration and execution paths succeed

**Dependencies**

- Agent 29
- Agent 31
- Agent 32

---

## Agent 37 — Audit and logging review

**Goal**
Perform a focused security/logging pass.

**Scope**

- confirm no secrets leak in logs/errors
- confirm request IDs and policy decisions are captured
- confirm DSNs/tokens/passwords are redacted everywhere

**Deliverables**

- fixes to logging/audit code
- review checklist/report

**Acceptance criteria**

- representative failure paths show no secret leakage

**Dependencies**

- Agent 09
- Agent 16
- Agent 36

---

## Agent 38 — Packaging and developer-experience review

**Goal**
Make the repo easy to run locally with `uv`.

**Scope**

- document `uv sync`
- document config file expectations
- document required env vars by backend
- add simple run/test commands

**Deliverables**

- updated README / developer docs

**Acceptance criteria**

- a new developer can bootstrap the project from docs

**Dependencies**

- Agent 01
- Agent 03
- Agent 32

---

## Parallelization Map

### Can start immediately after bootstrap

- Agent 02
- Agent 03

### Can run in parallel after structure exists

- Agent 04
- Agent 07
- Agent 08
- Agent 30

### Can run in parallel after config/models land

- Agent 05
- Agent 06
- Agent 10
- Agent 19

### Can run in parallel after shared bases land

- Agent 11
- Agent 12
- Agent 14
- Agent 15
- Agent 20

### Backend work that can parallelize heavily

- Agent 21
- Agent 22
- Agent 23
- then Agent 24 / 25 / 26 in parallel

### Final wiring sequence

- Agent 27 -> 28 -> 29 -> 31 -> 32 -> 36 -> 37 -> 38

---

## MVP Cut Line

If the team wants the smallest useful first delivery, stop after these tasks:

- Agent 01–29
- Agent 31
- Agent 32
- Agent 33
- Agent 34

That delivers:

- uv-based Python project
- config-driven connections
- readonly-by-default execution
- SQL Server / Snowflake / Databricks adapters
- core metadata tools
- `run_query`
- basic `explain_query`
- stdio transport

---

## Recommended Assignment Strategy

Use specialized agents rather than giving one agent broad ownership:

- **Platform/setup agents:** 01–03, 38
- **Schema/config agents:** 04–07
- **Safety/security agents:** 08–12, 16, 37
- **Service-layer agents:** 13–18
- **Adapter/platform agents:** 19–27
- **MCP integration agents:** 28–32, 36
- **Testing agents:** 33–36

This keeps each work item narrow, reviewable, and independently verifiable.

---

## Handoff Rules Between Agents

Each agent should leave behind:

1. the files it changed
2. a short summary of behavior added
3. any unresolved assumptions
4. explicit interfaces for the next dependent task
5. tests or at least usage examples where practical

Recommended handoff artifact format:

- **Changed files**
- **Public interfaces added/changed**
- **Open questions**
- **Next suggested agent**

---

## Notes on Future Expansion

These are intentionally **not** required for MVP, but the split plan leaves room for them later:

- long-running/background queries
- pagination/cursors
- richer observability/metrics
- per-connection RBAC
- saved query templates
- expanded Databricks SQLAlchemy support
- SQL Server `mssql-python` alternative driver path

---

## Summary

The plan is best executed as a sequence of small, explicit agent tasks with strong contracts:

- start with `uv` bootstrap and package skeleton
- define config/models/errors first
- build safety policy before query execution
- isolate backend behavior inside adapters/drivers
- expose a narrow stable MCP tool surface last
- test safety and normalization aggressively

This split should let multiple agents work concurrently without stepping on each other while preserving the architecture described in `PLAN.md`.
