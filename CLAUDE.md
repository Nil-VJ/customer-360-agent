# CLAUDE.md — Customer 360 Agent

Read `SPEC.md` first. It is the source of truth for scope, models, metrics and tests.
This file says how to work on it.

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
- **marts** (tables): `fct_orders`, `fct_order_items`, `dim_customer` (+ `fct_category_views` only if Q5 is in scope).
- Only marts are read by the agent.
- Every mart column has a description in YAML. Descriptions are read by humans and by the agent, so be precise.

## Partitioning and clustering (marts only)

- `fct_orders`, `fct_order_items`: partition by `ordered_at`, `granularity: month`; cluster by `customer_id`.
- `dim_customer`: no partitioning (one row per customer, small).
- Explain in the README that the data is small; this is the production pattern and it limits the agent's scan cost.

## Tests (keep to this list)

- Primary keys on every staging model and mart: `unique` + `not_null`.
- `accepted_values` on order and item `status` in staging (values confirmed in the day-1 checks).
- `relationships`: `fct_orders.customer_id` and `fct_order_items.customer_id` → `dim_customer`.
- RFM scores between 1 and 5 (`dbt_utils.accepted_range` or a short singular test).
- One singular test: total net revenue in `fct_orders` equals `fct_order_items` (tolerance 0.01).
- Optional: source freshness on `orders.created_at` as **warn** only.

## Agent rules

- Agent logic is a plain Python function `answer(question) -> (text, sql, rows)`.
  Streamlit (`app.py`) only wraps it, so a command-line fallback is trivial.
- Context = mart table and column descriptions from `target/manifest.json` + metric definitions from the semantic YAML.
- Tool `run_sql(query)`:
  1. BigQuery dry run first. Reject unless statement type is SELECT and every referenced table is in `c360_marts`.
     (Check that the dry-run job exposes these; if not, fall back to parsing with `sqlglot` and ask me first.)
  2. Run with `maximum_bytes_billed` = 1 GB; add `LIMIT 200` if missing.
  3. Return rows as JSON, max 200.
- If a query fails twice or the question is outside the marts, say so instead of guessing.
- Every answer shows the SQL it ran and any assumption (e.g. date window).
- API key from `.env` (`ANTHROPIC_API_KEY`); `.env` is in `.gitignore`.

## Phases

1. **Scaffold + staging:** repo layout, requirements, `.gitignore`, dbt project, sources, staging models + tests. `dbt build` green.
2. **Intermediate + marts:** models, partition/cluster config, relationship/RFM/reconciliation tests. `dbt build` green.
3. **Semantic layer:** semantic models, metrics, `metricflow_time_spine`. `dbt parse` passes.
4. **Agent:** `answer()`, `run_sql` guardrails, Streamlit app, eval script over the cases in SPEC.md.
5. **README:** what it is, architecture (text diagram), how to run, decisions, eval results, limitations.

Hard stop for building: Thursday 12:00. Anything unfinished is dropped, not rushed.
