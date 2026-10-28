"""Customer 360 agent: answers marketing questions with SQL over the dbt marts and MetricFlow metrics.

Usage:
    python agent.py                      # interactive loop
    python agent.py "your question"      # one question, then exit
"""

import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from google.cloud import bigquery

MODEL = "claude-opus-5-5"
PROJECT_DIR = Path(__file__).parent
MANIFEST_PATH = PROJECT_DIR / "target" / "manifest.json"
SEMANTIC_MANIFEST_PATH = PROJECT_DIR / "target" / "semantic_manifest.json"
MF_BIN = Path(sys.executable).parent / "mf"  # MetricFlow CLI installed in the same venv
TIME_SPINE = "metricflow_time_spine"  # used by MetricFlow only, so not shown to the model as a table
MARTS_PROJECT = "ecommerce-customer-360"
MARTS_DATASET = "c360_marts"
MAX_BYTES = 1_000_000_000  # 1 GB
MAX_ROWS = 200
MAX_FAILED_QUERIES = 2
MAX_TOOL_CALLS = 6

RUN_SQL_TOOL = {
    "name": "run_sql",
    "description": (
        "Run one BigQuery Standard SQL SELECT statement against the mart tables and return the rows as JSON "
        "(at most 200 rows). Only SELECT is allowed, and only tables in the c360_marts dataset. "
        "Use fully qualified table names in backticks. A LIMIT 200 is added if the query has none."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "A single SELECT statement."}},
        "required": ["query"],
    },
}

QUERY_METRIC_TOOL = {
    "name": "query_metric",
    "description": (
        "Compute defined metrics from the semantic layer with MetricFlow and return the rows as JSON "
        "(at most 200 rows). MetricFlow writes the SQL; it then runs through the same checks as run_sql. "
        "Use the metric and dimension names listed in the system prompt exactly."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "metrics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Metric names, for example [\"avg_order_value\", \"repeat_customer_rate\"].",
            },
            "group_by": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Dimensions to group by, for example [\"customer__country\", \"order_item__category\", "
                    "\"metric_time__quarter\"]."
                ),
            },
            "where": {
                "type": "string",
                "description": (
                    "Optional filter in MetricFlow syntax, for example "
                    "\"{{ Dimension('customer__is_repeat') }} = true\" or "
                    "\"{{ Dimension('customer__country') }} = 'Brasil'\"."
                ),
            },
            "start_time": {"type": "string", "description": "Optional first day of the window, YYYY-MM-DD, inclusive."},
            "end_time": {"type": "string", "description": "Optional last day of the window, YYYY-MM-DD, inclusive."},
            "order_by": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional sort, metric or dimension names. Prefix with - for descending: [\"-net_revenue\"].",
            },
            "limit": {"type": "integer", "description": "Optional maximum number of rows."},
        },
        "required": ["metrics"],
    },
}

ANSWER_RULES = """\
You answer questions from an e-commerce marketing director with two tools:
query_metric for the defined metrics below, and run_sql for SQL on the mart tables below.

Rules:
- Use a tool for every question about the data. Never invent numbers.
- If the question asks for a defined metric (net revenue, orders, active customers, AOV, gross margin,
  repeat customer rate), use query_metric, grouped by dimensions and limited to a date window as needed.
- Use run_sql for everything else: customer lists, counts or shares of customers that are not defined
  metrics, and columns the semantic layer does not expose. If query_metric fails because a dimension
  or filter is not available, use run_sql instead.
- Use only the tables and columns listed below. They contain no emails, names or addresses,
  so decline any request for personal contact data.
- You report history only. Do not forecast or predict future values.
- If a question is vague, either ask which metric and period the user means,
  or pick a sensible default and state it.
- If the question cannot be answered from these tables, say so instead of guessing.
- Use the metric definitions below and in the column descriptions (net revenue, AOV, repeat rate,
  high-value customer).
- Date windows are measured from today's date, which is given with each question:
  "last N days" = the N days before today; "last quarter" = the previous full calendar quarter.
- Shares and rates use customers with at least one order as the denominator unless the question says otherwise.
- Keep the answer short: lead with the result, then list every assumption you made
  (date window, definitions, filters). The SQL is shown to the user separately.
"""


def load_mart_context(manifest_path=MANIFEST_PATH):
    """Build the table and column description text from the dbt manifest."""
    if not manifest_path.exists():
        sys.exit(f"Missing {manifest_path}. Run `dbt parse` (or `dbt build`) first.")
    manifest = json.loads(manifest_path.read_text())

    lines = []
    for node in manifest["nodes"].values():
        if node["resource_type"] != "model" or node["schema"] != MARTS_DATASET or node["name"] == TIME_SPINE:
            continue
        table = f"`{node['database']}.{node['schema']}.{node['alias']}`"
        lines.append(f"\nTable {table}\n{node['description'].strip()}\nColumns:")
        for column in node["columns"].values():
            lines.append(f"- {column['name']}: {column['description'].strip()}")
    return "\n".join(lines)


def load_metric_context(semantic_manifest_path=SEMANTIC_MANIFEST_PATH):
    """Build the metric and dimension list from MetricFlow's semantic manifest."""
    if not semantic_manifest_path.exists():
        sys.exit(f"Missing {semantic_manifest_path}. Run `dbt parse` first.")
    manifest = json.loads(semantic_manifest_path.read_text())

    lines = ["\nMetrics (use with query_metric):"]
    for metric in manifest["metrics"]:
        lines.append(f"- {metric['name']} ({metric['type']}): {' '.join(metric['description'].split())}")

    lines.append("\nDimensions (use in group_by and where, written as entity__dimension):")
    for model in manifest["semantic_models"]:
        entity = next(e["name"] for e in model["entities"] if e["type"] == "primary")
        for dimension in model["dimensions"]:
            if dimension["type"] == "time":
                continue
            lines.append(f"- {entity}__{dimension['name']}: {dimension['description']}")
    lines.append(
        "- metric_time__day, metric_time__week, metric_time__month, metric_time__quarter, metric_time__year: "
        "the order date for order and item metrics. start_time and end_time filter on it."
    )
    return "\n".join(lines)


SYSTEM_PROMPT = None  # built on first use, so importing this module needs no manifest
_bq_client = None
_claude_client = None


def get_bq_client():
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=MARTS_PROJECT, location="US")
    return _bq_client


def get_claude_client():
    global _claude_client
    if _claude_client is None:
        load_dotenv()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to a .env file at the repo root.")
        _claude_client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    return _claude_client


def check_query(query):
    """Dry run the query. Return an error message, or None if it is allowed."""
    config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    try:
        job = get_bq_client().query(query, job_config=config)
    except Exception as error:
        return f"Query is not valid: {getattr(error, 'message', error)}"

    if job.statement_type != "SELECT":
        return f"Rejected: only SELECT is allowed, this is {job.statement_type}."
    tables = job.referenced_tables
    if not tables:
        return f"Rejected: the query must read from tables in {MARTS_DATASET}."
    outside = [
        f"{t.project}.{t.dataset_id}.{t.table_id}"
        for t in tables
        if (t.project, t.dataset_id) != (MARTS_PROJECT, MARTS_DATASET)
    ]
    if outside:
        return f"Rejected: only tables in {MARTS_DATASET} may be read, not {', '.join(outside)}."
    if job.total_bytes_processed > MAX_BYTES:
        return f"Rejected: the query would scan {job.total_bytes_processed:,} bytes, over the 1 GB limit."
    return None


def add_limit(query):
    """Append LIMIT 200 if the query does not already end with a LIMIT."""
    if re.search(r"\blimit\s+\d+\s*$", query, flags=re.IGNORECASE):
        return query
    return f"{query}\nLIMIT {MAX_ROWS}"


def run_sql(query):
    """Validate and run a query. Return (rows, sql_ran, error). Exactly one of rows or error is set."""
    query = query.strip().rstrip(";").strip()
    error = check_query(query)
    if error:
        return None, None, error

    query = add_limit(query)
    config = bigquery.QueryJobConfig(
        maximum_bytes_billed=MAX_BYTES,
        labels={"project": "customer_360", "purpose": "agent"},
    )
    try:
        result = get_bq_client().query(query, job_config=config).result(max_results=MAX_ROWS)
        rows = [dict(row.items()) for row in result]
    except Exception as error:
        return None, None, f"Query failed: {getattr(error, 'message', error)}"
    return rows, query, None


def join_queries(queries):
    """Combine every (tool, query) that ran into one SQL text, each labelled with the tool that made it."""
    if not queries:
        return None
    if len(queries) == 1:
        tool, query = queries[0]
        return f"-- via {tool}\n{query}"
    return "\n\n".join(
        f"-- Query {i} of {len(queries)}, via {tool}\n{query};" for i, (tool, query) in enumerate(queries, start=1)
    )


def as_list(value):
    """Accept a single string or a list of strings."""
    if not value:
        return []
    return [value] if isinstance(value, str) else [str(v) for v in value]


def query_metric(tool_input):
    """Let MetricFlow write the SQL for the requested metrics, then run it through run_sql's checks.

    Return (rows, sql_ran, error), like run_sql.
    """
    metrics = as_list(tool_input.get("metrics"))
    if not metrics:
        return None, None, "Give at least one metric name."

    args = [str(MF_BIN), "query", "--metrics", ",".join(metrics)]
    if tool_input.get("group_by"):
        args += ["--group-by", ",".join(as_list(tool_input["group_by"]))]
    if tool_input.get("where"):
        args += ["--where", tool_input["where"]]
    if tool_input.get("start_time"):
        args += ["--start-time", tool_input["start_time"]]
    if tool_input.get("end_time"):
        args += ["--end-time", tool_input["end_time"]]
    if tool_input.get("order_by"):
        args += ["--order", ",".join(as_list(tool_input["order_by"]))]
    if tool_input.get("limit"):
        args += ["--limit", str(int(tool_input["limit"]))]
    args += ["--explain", "--quiet"]  # print the SQL only; run_sql executes it

    # MetricFlow needs the dbt profile, not the Anthropic key.
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    env.setdefault("DBT_PROFILES_DIR", str(Path.home() / ".dbt"))
    try:
        result = subprocess.run(args, cwd=PROJECT_DIR, env=env, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return None, None, "MetricFlow timed out."

    output = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout + result.stderr).strip()
    if result.returncode != 0 or not re.match(r"(with|select)\b", output, flags=re.IGNORECASE):
        return None, None, f"MetricFlow could not build this query: {output[-1500:]}"
    return run_sql(output)


def answer(question):
    """Answer one question. Return (text, sql, rows).

    sql holds every query that ran, in order, labelled with its tool. rows are from the last successful query.
    """
    global SYSTEM_PROMPT
    if SYSTEM_PROMPT is None:
        SYSTEM_PROMPT = ANSWER_RULES + load_metric_context() + "\n\nMart tables:\n" + load_mart_context()

    today = datetime.date.today().isoformat()
    messages = [{"role": "user", "content": f"Today is {today}.\n\nQuestion: {question}"}]
    queries, rows = [], None
    failed_queries, tool_calls = 0, 0

    while True:
        response = get_claude_client().messages.create(
            model=MODEL,
            max_tokens=16000,
            output_config={"effort": "high"},
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=[QUERY_METRIC_TOOL, RUN_SQL_TOOL],
            messages=messages,
        )
        text = "\n".join(block.text for block in response.content if block.type == "text").strip()

        if response.stop_reason != "tool_use":
            if response.stop_reason == "max_tokens":
                text += "\n\n(Answer cut off: the model hit its output limit.)"
            elif response.stop_reason == "refusal":
                text = text or "The model declined to answer this question."
            return text, join_queries(queries), rows

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            tool_calls += 1
            if block.name == "query_metric":
                query_rows, query_ran, error = query_metric(block.input)
            else:
                query_rows, query_ran, error = run_sql(block.input.get("query", ""))
            if error:
                failed_queries += 1
                content, is_error = error, True
            else:
                queries.append((block.name, query_ran))
                rows = query_rows
                content, is_error = json.dumps(query_rows, default=str), False
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": content, "is_error": is_error}
            )

            if failed_queries >= MAX_FAILED_QUERIES:
                text = f"I could not answer this: the query failed twice. Last error: {error}"
                return text, join_queries(queries), rows
        if tool_calls >= MAX_TOOL_CALLS:
            return "I could not answer this within the query limit for one question.", join_queries(queries), rows
        messages.append({"role": "user", "content": tool_results})


def format_rows(rows, max_shown=20):
    """Render rows as a small plain-text table."""
    if not rows:
        return "(no rows)"
    columns = list(rows[0].keys())
    shown = [[str(row[c]) for c in columns] for row in rows[:max_shown]]
    widths = [max(len(c), *(len(r[i]) for r in shown)) for i, c in enumerate(columns)]
    lines = [
        " | ".join(c.ljust(w) for c, w in zip(columns, widths)),
        "-+-".join("-" * w for w in widths),
        *(" | ".join(v.ljust(w) for v, w in zip(r, widths)) for r in shown),
    ]
    if len(rows) > max_shown:
        lines.append(f"... {len(rows) - max_shown} more rows")
    return "\n".join(lines)


def print_answer(question):
    text, sql, rows = answer(question)
    print(f"\n{text}\n")
    print("SQL:\n" + (sql or "(no query run)") + "\n")
    if rows is not None:
        print(format_rows(rows) + "\n")


def main():
    if len(sys.argv) > 1:
        print_answer(" ".join(sys.argv[1:]))
        return
    print("Customer 360 agent. Ask a question, or press Enter to quit.")
    while True:
        try:
            question = input("\nQuestion> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            break
        print_answer(question)


if __name__ == "__main__":
    main()
