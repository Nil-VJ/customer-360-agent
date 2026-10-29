# CLAUDE.md — Customer 360 Agent

Read `SPEC.md` first. It is the source of truth for scope, models, metrics and tests.
This file says how to work on it.

## How to talk to me

- Use simple, plain words. Explain any technical term in one short phrase the first time.
- Keep answers short: lead with the answer, then at most a few bullets. No long paragraphs.
- I am a visual person: show, don't only tell.
  - In the terminal: small ASCII diagrams for flows and model lineage, and tables for comparisons and options.
  - For anything worth keeping (architecture, model lineage, data flow), write a Mermaid diagram into a Markdown file
    under `docs/` so it renders on GitHub.
  - When explaining data (row counts, distributions, test results), show a small table or ASCII bar chart, not only prose.

## How we work

- Work in phases (below). Use plan mode first. After each phase, STOP and wait for my review.
- After each phase, explain every design decision in at most 5 bullets: what you chose, the alternative, and why.
- Build only what SPEC.md lists. No extra models, macros, packages, abstractions or config "for later".
- Ask before adding any dependency not listed here.
- Prefer plain, readable SQL over clever SQL. One CTE per logical step, named for what it does.
- Never print, log or commit secrets.

## Stack

- dbt Core + dbt-bigquery (pin exact versions in `requirements.txt`)
- Python 3.11+, `anthropic`, `google-cloud-bigquery`, `streamlit`, `python-dotenv`
- Agent model: `claude-opus-5-5`
- Optional: `dbt-metricflow` for the `mf` CLI. If it is fiddly, skip it (see SPEC.md).

## BigQuery

- Source: `bigquery-public-data.thelook_ecommerce`. It lives in the **US** multi-region.
  All target datasets must also be in **US**, or queries across locations fail.
- Datasets: `c360_staging`, `c360_intermediate`, `c360_marts` (via `+schema` in dbt_project.yml).
- Local auth: `gcloud auth application-default login` (dbt `method: oauth`). No key files in the repo.
- `profiles.yml` lives in `~/.dbt/`, never in the repo.

## dbt layer rules

- **staging** (views): one model per source table. Rename, cast, standardise. No joins, no business logic.
  Drop PII here: `first_name`, `last_name`, `email`, `street_address`, `postal_code`, `latitude`, `longitude`.
- **intermediate** (views): joins and business logic (product category, unit cost, `is_net_revenue` flag).
  Net revenue = items with status Complete, Shipped or Processing. Cancelled and Returned are excluded.
- **marts** (tables): `fct_orders`, `fct_order_items`, `dim_customer`. `fct_category_views` (question 5) is built in Phase 5.
- Only marts are read by the agent.
- Every mart column has a description in YAML. Descriptions are read by humans and by the agent, so be precise.

## Partitioning and clustering (marts only)

- `fct_orders`, `fct_order_items`: partition by `ordered_at`, `granularity: month`; cluster by `customer_id`.
- `dim_customer`: no partitioning (one row per customer, small).
- The data is small (about 125k orders, 182k order items, 100k users). Explain in the README that this is the
  production pattern and that it limits the agent's scan cost, not a performance need at this size.

## Tests (keep to this list)

- Primary keys on every staging model and mart: `unique` + `not_null`.
- `accepted_values` on order and item `status` in staging: Cancelled, Complete, Processing, Returned, Shipped.
- `relationships`: `fct_orders.customer_id` and `fct_order_items.customer_id` → `dim_customer`.
- RFM scores between 1 and 5 (`dbt_utils.accepted_range` or a short singular test).
- One singular test: total net revenue in `fct_orders` equals `fct_order_items` (tolerance 0.01).
- Optional: source freshness on `orders.created_at` as **warn** only.

## Agent rules

- Agent logic is a plain Python function `answer(question) -> (text, sql, rows)`.
  It runs first as a command-line loop (`python agent.py`). Streamlit (`app.py`) wraps it in Phase 5.
- Context = metric and dimension definitions from `target/semantic_manifest.json`, plus mart table and column
  descriptions from `target/manifest.json` (the time spine is hidden).
- Two tools:
  - `query_metric(metrics, group_by, where, start_time, end_time, order_by, limit)`: runs `mf query --explain`,
    so MetricFlow writes the SQL from the semantic layer YAML. It does not run the SQL itself.
  - `run_sql(query)`: SQL the model writes on the marts.
- Routing: defined metrics (net revenue, orders, active customers, AOV, gross margin, repeat customer rate)
  go to `query_metric`. Everything else (customer lists, other counts and shares) goes to `run_sql`,
  which is also the fallback when a dimension or filter is not in the semantic layer.
- One guard for both tools. Every query, including MetricFlow's, goes through `run_sql`:
  1. BigQuery dry run first. Reject unless statement type is SELECT and every referenced table is in `c360_marts`.
  2. Run with `maximum_bytes_billed` = 1 GB; add `LIMIT 200` if missing.
  3. Return rows as JSON, max 200.
- If a query fails twice or the question is outside the marts, say so instead of guessing.
- Every answer shows every query it ran, labelled with its tool, and any assumption (e.g. date window).
- API key from `.env` (`ANTHROPIC_API_KEY`); `.env` is in `.gitignore`.

## Phases

Data facts (day-1 checks, 21 Oct): orders run 7 Jan 2019 to today; 46% of web events have no `user_id`.
Windows like "last 90 days" are measured from the current date.

There is no deadline. This project is a priority. Work through the phases in order and stop for review after each one.

1. **Phase 1, scaffold + staging:** repo layout, requirements, `.gitignore`, dbt project, sources, staging models + tests. `dbt build` green.
2. **Phase 2, intermediate + marts:** models, partition/cluster config, relationship/RFM/reconciliation tests. `dbt build` green.
3. **Phase 3, minimal agent:** `answer()`, `run_sql` guardrails, command-line loop, the five eval cases.
4. **Phase 4, semantic layer:** MetricFlow semantic models, metrics, `metricflow_time_spine`. `dbt parse` passes.
5. **Phase 5, app and stretch question:** Streamlit app, question 5 (`fct_category_views`), full eval run.
6. **Phase 6, README:** what it is, architecture, how to run, decisions, eval results, limitations.
