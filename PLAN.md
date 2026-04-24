# Universal Database MCP Server Plan

## Goal
Build a Python MCP server that supports:
- Microsoft SQL Server
- Snowflake
- Databricks

The server should let an agent safely inspect metadata and run queries across multiple configured database connections through one consistent MCP interface.

---

## Core Recommendation

### Language and framework
- **Python 3.12+**
- **Official `mcp` Python SDK**
- **FastMCP** for the server layer

### Database strategy
Use a **hybrid adapter architecture**:
- **SQLAlchemy Core** as the common abstraction where it fits well
- **Native vendor connectors** where they are stronger than a pure SQLAlchemy path

### Driver choices
- **SQL Server:** `pyodbc` via SQLAlchemy
  - optional future support: `mssql-python`
- **Snowflake:** `snowflake-sqlalchemy`
- **Databricks:** `databricks-sql-connector` as primary
  - optional future support: `databricks-sqlalchemy`

### Supporting libraries
- `pydantic` for config and request/response validation
- `sqlglot` for SQL parsing, statement classification, and safety checks
- `tenacity` for retry/backoff
- `orjson` for efficient JSON serialization

---

## Architectural Principles

1. **Stable MCP interface**
   - Tools exposed to the agent should remain consistent across all databases.

2. **Adapter isolation**
   - Each database backend gets its own adapter.
   - Backend-specific quirks stay inside the adapter layer.

3. **Read-only by default**
   - Query execution defaults to read-only behavior.
   - Unsafe operations are blocked unless explicitly enabled.

4. **Config-driven connections**
   - All connections are declared in configuration.
   - Secrets are provided through environment variables.

5. **Safety before convenience**
   - Parse SQL before execution.
   - Enforce statement restrictions, limits, timeouts, and result truncation.

---

## High-Level Architecture

### 1. MCP layer
Responsibilities:
- register MCP tools/resources/prompts
- validate tool input
- call service layer
- format MCP responses

Implementation:
- `mcp`
- `mcp.server.fastmcp.FastMCP`

### 2. Service layer
Responsibilities:
- connection lookup
- request validation
- safety policy enforcement
- query orchestration
- metadata normalization
- audit logging
- error normalization

### 3. Adapter layer
Responsibilities:
- build connections/engines
- enumerate schemas/tables/columns
- execute queries
- explain queries
- map backend-specific behavior to shared result models

### 4. Driver/dialect layer
Responsibilities:
- actual wire/database communication

---

## Concrete Backend Plan

### SQL Server adapter
**Primary implementation:**
- SQLAlchemy Core
- `mssql+pyodbc`

**Optional future support:**
- `mssql+mssqlpython`

**Why:**
- mature SQLAlchemy support
- proven production usage
- strong reflection support

### Snowflake adapter
**Primary implementation:**
- SQLAlchemy Core
- `snowflake-sqlalchemy`

**Why:**
- official SQLAlchemy path
- clean integration with a shared abstraction

### Databricks adapter
**Primary implementation:**
- `databricks-sql-connector`

**Optional future support:**
- `databricks-sqlalchemy`

**Why:**
- official Databricks connector
- strong auth support
- native parameterized query support
- better fit than forcing everything through SQLAlchemy alone

---

## MCP Tool Surface

Start with these tools:

### `list_connections`
Returns configured connections.

### `test_connection`
Tests a specific connection and returns status and backend details when available.

### `list_schemas`
Lists catalogs/schemas for a connection.

### `list_tables`
Lists tables/views within a schema.

### `describe_table`
Returns column and table metadata.

### `run_query`
Executes a SQL statement subject to policy and limit enforcement.

### `explain_query`
Returns a query plan where supported.

---

## Query Permission Model

### Default behavior: READONLY
All query execution should be **read-only by default**.

That means:
- permit `SELECT`
- permit safe metadata access
- optionally permit safe `EXPLAIN`
- block all write or schema-changing statements by default

### Explicit opt-in for full permissions
Add an explicit option to the execution request, for example:
- `permission_mode: "readonly" | "full"`

Default:
- `permission_mode = "readonly"`

Only when the caller explicitly requests:
- `permission_mode = "full"`

...should the server allow execution using the **full effective permissions of the configured database user**.

### Important guardrail
Even when `permission_mode="full"`, the server should still enforce:
- single-statement restrictions unless explicitly relaxed
- timeouts
- row/result-size limits where applicable
- audit logging
- optional connection-level allow/deny policies

### Recommended policy
Use both:
1. a **request-level flag** (`permission_mode="full"`)
2. a **connection-level capability flag** (`allow_full_permissions: true/false`)

This prevents accidental escalation on connections that should always remain read-only.

### Effective rule
A non-read-only query should only run when **both** are true:
- the request explicitly sets `permission_mode="full"`
- the target connection is configured with `allow_full_permissions: true`

Otherwise the query is treated as read-only and blocked if it contains non-read-only statements.

---

## Readonly Policy Rules

### Allowed by default
- `SELECT`
- backend-safe metadata discovery statements generated internally
- `EXPLAIN` / plan inspection if enabled

### Blocked by default
- `INSERT`
- `UPDATE`
- `DELETE`
- `MERGE`
- `UPSERT`
- `COPY INTO`
- `CREATE`
- `ALTER`
- `DROP`
- `TRUNCATE`
- `GRANT`
- `REVOKE`
- stored procedure execution
- multiple statements separated by `;`

### Full-permission mode
When full permission mode is explicitly enabled and allowed for the connection, the server may permit these statements according to connection policy.

---

## Query Execution Pipeline

For `run_query` and `explain_query`:

1. Validate tool input
   - connection exists
   - SQL present
   - timeout within bounds
   - row limit within bounds
   - permission mode valid

2. Resolve connection configuration
   - load secrets from environment
   - create adapter instance

3. Parse SQL with `sqlglot`
   - classify statement type
   - detect multiple statements
   - detect DDL/DML/destructive operations
   - detect unsupported constructs

4. Enforce policy
   - if `permission_mode="readonly"`, only allow read-only statements
   - if `permission_mode="full"`, verify connection allows full permissions
   - apply connection-specific policy overrides

5. Execute query
   - use backend adapter
   - apply timeout
   - fetch up to `max_rows + 1`

6. Normalize results
   - columns
   - rows
   - elapsed time
   - truncation warnings
   - backend metadata such as query id

7. Audit log
   - request id
   - connection name
   - statement fingerprint
   - statement type
   - permission mode
   - success/failure
   - elapsed time

8. Return structured MCP response

---

## Normalized Data Model

### Unified naming
Use these cross-backend fields:
- `catalog`
- `schema`
- `name`
- `object_type`

### Mapping
- SQL Server: database -> `catalog`, schema -> `schema`
- Snowflake: database -> `catalog`, schema -> `schema`
- Databricks: catalog -> `catalog`, schema -> `schema`

### Query result shape
Return:
- column metadata
- rows as arrays for compactness
- row count
- truncated flag
- elapsed time
- warnings
- backend metadata

---

## Configuration Strategy

Use:
- **YAML** for human-managed config
- **env vars** for secrets

### Example config
```yaml
server:
  name: universal-db-mcp
  transport: stdio
  log_level: info

defaults:
  permission_mode: readonly
  timeout_ms: 30000
  max_rows: 500
  max_bytes: 1048576
  allow_multiple_statements: false
  block_destructive_sql: true

connections:
  app_sqlserver:
    type: sqlserver
    driver: pyodbc
    description: Main application SQL Server
    read_only: true
    allow_full_permissions: false
    dsn_env: APP_SQLSERVER_DSN

  warehouse_sf:
    type: snowflake
    description: Snowflake analytics warehouse
    read_only: true
    allow_full_permissions: false
    account_env: SNOWFLAKE_ACCOUNT
    user_env: SNOWFLAKE_USER
    password_env: SNOWFLAKE_PASSWORD
    warehouse_env: SNOWFLAKE_WAREHOUSE
    database: ANALYTICS
    schema: PUBLIC
    role_env: SNOWFLAKE_ROLE

  dbx_prod:
    type: databricks
    description: Databricks SQL warehouse
    read_only: true
    allow_full_permissions: false
    server_hostname_env: DATABRICKS_SERVER_HOSTNAME
    http_path_env: DATABRICKS_HTTP_PATH
    token_env: DATABRICKS_TOKEN
    catalog: main
    schema: analytics
```

### Notes
- `read_only: true` means the connection should be treated as readonly by policy.
- `allow_full_permissions: false` means request-level escalation is not allowed.
- To permit full user privileges for a trusted connection, set:
  - `allow_full_permissions: true`

---

## Suggested Python Package Layout

```txt
src/db_mcp_server/
  __init__.py
  main.py
  server.py

  config/
    models.py
    loader.py
    secrets.py

  mcp/
    tools.py
    resources.py
    prompts.py
    schemas.py

  services/
    connection_registry.py
    query_service.py
    metadata_service.py
    validation_service.py
    audit_service.py
    result_formatter.py

  adapters/
    base.py
    sqlalchemy_base.py
    sqlserver.py
    snowflake.py
    databricks.py

  drivers/
    sqlserver_engine.py
    snowflake_engine.py
    databricks_client.py

  safety/
    sql_parser.py
    policies.py
    limits.py
    errors.py

  models/
    connection.py
    query.py
    result.py
    metadata.py

  util/
    logging.py
    timing.py
    retry.py
    redact.py
```

---

## Core Interfaces

### Adapter interface
```python
class DatabaseAdapter(Protocol):
    def test_connection(self) -> ConnectionTestResult: ...
    def list_schemas(self) -> list[SchemaInfo]: ...
    def list_tables(self, catalog: str | None, schema: str | None, include_views: bool) -> list[TableInfo]: ...
    def describe_table(self, catalog: str | None, schema: str, table: str) -> TableDescription: ...
    def run_query(self, sql: str, params: dict[str, Any], options: QueryOptions) -> QueryResult: ...
    def explain_query(self, sql: str, params: dict[str, Any], options: QueryOptions) -> ExplainResult: ...
```

### Service interface
```python
class QueryService:
    def run_query(self, request: RunQueryRequest) -> RunQueryResponse: ...
```

---

## Error Model

Normalize errors into stable codes:
- `UNKNOWN_CONNECTION`
- `CONNECTION_FAILED`
- `AUTH_FAILED`
- `QUERY_BLOCKED`
- `QUERY_TIMEOUT`
- `QUERY_TOO_LARGE`
- `INVALID_SQL`
- `UNSUPPORTED_OPERATION`
- `BACKEND_ERROR`

Avoid leaking raw driver exceptions directly to MCP clients.

---

## Logging and Audit Requirements

For each tool call, log:
- request id
- tool name
- connection
- statement type
- permission mode
- policy decision
- success/failure
- elapsed ms
- row count
- truncation

Never log:
- raw passwords
- tokens
- full secret env values
- unredacted DSNs

---

## Transport Plan

### Development
- `stdio`

### Production / remote deployment
- Streamable HTTP

Support both via startup options:
- `--transport stdio`
- `--transport streamable-http --host 0.0.0.0 --port 8000`

---

## Concurrency and Connection Management

### SQLAlchemy-backed adapters
Use engine pooling with conservative defaults:
- small pool size
- max overflow
- pre-ping enabled

### Databricks adapter
Start with simpler per-request connections unless profiling shows a need for pooling.

---

## Implementation Phases

### Phase 1: MVP
Build:
- `list_connections`
- `test_connection`
- `list_schemas`
- `list_tables`
- `describe_table`
- `run_query`
- readonly-by-default policy
- explicit `permission_mode="full"` support behind config gate
- stdio transport
- SQL Server + Snowflake + Databricks adapters

### Phase 2: hardening
Add:
- Streamable HTTP
- audit logging
- metrics
- retries
- `explain_query`
- MCP resources
- better auth support

### Phase 3: advanced features
Add:
- long-running background query support
- pagination/cursors
- saved query templates
- per-connection RBAC
- richer observability

---

## Recommended Day-1 Dependency Set

```txt
mcp
sqlalchemy>=2.0
pydantic>=2
sqlglot
tenacity
orjson
pyodbc
snowflake-sqlalchemy
databricks-sql-connector[pyarrow]
databricks-sqlalchemy
```

Optional:
```txt
mssql-python
structlog
prometheus-client
uvicorn
fastapi
```

---

## Final Recommendation

Build the server as:
- **FastMCP server**
- **service layer**
- **adapter layer**
- **per-database driver integrations**

Use:
- **SQL Server -> `pyodbc` + SQLAlchemy**
- **Snowflake -> `snowflake-sqlalchemy`**
- **Databricks -> `databricks-sql-connector` first**

And enforce this execution rule:

> All queries are **READONLY by default**.
> Only allow full user permissions when the caller explicitly requests it with `permission_mode="full"` **and** the target connection configuration permits full-permission execution.
