# Customer 360 Agent — Technical Spec

Oct 20, 2026 · @Niloufar Valinejad

## Overview

Build a customer-360 model in dbt on BigQuery's public e-commerce dataset, a semantic layer on top, and a chat agent that answers marketing questions through governed SQL. Timebox: Tue 20 to Thu 22 Oct 2026, with a hard stop for the build at Thu 12:00.

Why: it closes the two gaps raised in the Columbia Road interview (e-commerce customer data, AI on top of data) and gives a concrete architecture to draw on the whiteboard on Fri 23 Oct. It is equally relevant to Behavix.

Done means: the five business questions below are answered correctly by the agent, `dbt build` passes, and a public repo has a README with the architecture diagram.

## Scope and non-goals

The build covers modeling, a semantic layer and one agent tool.

**In scope**

- Read-only use of the public dataset.
- dbt Core on BigQuery: staging, intermediate and mart models, with tests and column descriptions
- MetricFlow metrics and a time spine
- A Python chat agent using the Claude API with one tool that runs read-only SQL on the marts
- README with the architecture diagram and evaluation results

**Not in scope (phase 2, after the interview)**

- Ingestion pipeline and scheduled refresh (hourly or daily)
- Dashboard or web app
- RAG and a vector database
- Recommendation models
- Deployment, authentication, production hardening

## Business questions

The persona is an e-commerce marketing director planning email campaigns. Every model and metric must serve at least one of these questions.

| # | Question | Marketing use | Answered from |
| --- | --- | --- | --- |
| 1 | How many high-value customers have not bought in 90+ days? | Win-back audience | dim\_customer (RFM segment, days since last order) |
| 2 | Which product categories bring the most revenue from repeat customers last quarter? | Cross-sell and newsletter content | fct\_order\_items + dim\_customer |
| 3 | What share of customers bought only once, by acquisition traffic source? | Channel quality | dim\_customer |
| 4 | What are average order value and repeat rate by country and age band? | Segment targeting | fct\_orders + dim\_customer |
| 5 (stretch) | Which customers viewed a category in the last 30 days but never bought in it? | Browse-abandonment audience | fct\_category\_views + fct\_order\_items |

"Last 90 days" and "last quarter" are measured from the dataset's latest order date, not today, unless day-1 checks show the data is current.

## Architecture

Data moves through dbt into marts; the agent reads only those marts through one guarded tool, using the semantic layer's definitions as context.

&#91;embedded content: architecture · dbt layers, semantic layer, agent\]

Raw tables and PII never reach the agent: staging drops them, and the agent's service account can only read the marts dataset.

## Data source

The source is `bigquery-public-data.thelook_ecommerce`, a synthetic clothing webshop with seven related tables ([Towards AI walkthrough](https://pub.towardsai.net/designing-a-scalable-production-ready-e-commerce-database-in-bigquery-472dde11dce9)). Six are used; `distribution_centers` is not.

| Table | Grain | Used for | Notes |
| --- | --- | --- | --- |
| users | One row per customer | Customer attributes: age, gender, country, traffic source, signup date | Holds email, names and address. These PII columns are dropped in staging |
| orders | One row per order | Order status and timestamps | Status values include Complete, Cancelled, Returned |
| order\_items | One row per item sold | Revenue (`sale_price` at time of purchase), item status | Carries its own `user_id` |
| inventory\_items | One row per physical unit | Unit cost for margin | Join path: order\_items → inventory\_items → products |
| products | One row per product | Category, brand, department, retail price |  |
| events | One row per web event | Category views for question 5 | `event_type` includes home, product, cart, purchase |

**Day-1 checks (Tue evening):** confirm column names in the console, the latest `created_at` in orders, the full list of status values, and the share of events with a `user_id`.

## dbt models

Three layers: staging views clean and rename, intermediate views hold business logic, mart tables are what the agent may query. Marts live in their own dataset so the agent's permissions can be limited to it.

| Model | Layer | Grain | Key columns | Tests |
| --- | --- | --- | --- | --- |
| stg\_users | staging (view) | customer | customer\_id, age, gender, country, traffic\_source, signed\_up\_at | unique and not\_null on customer\_id |
| stg\_orders | staging (view) | order | order\_id, customer\_id, status, ordered\_at, returned\_at | unique, not\_null, accepted\_values on status |
| stg\_order\_items | staging (view) | order item | order\_item\_id, order\_id, customer\_id, product\_id, inventory\_item\_id, status, sale\_price | unique, not\_null |
| stg\_products | staging (view) | product | product\_id, category, brand, department, retail\_price | unique, not\_null |
| stg\_inventory\_items | staging (view) | physical unit | inventory\_item\_id, product\_id, cost | unique, not\_null |
| stg\_events | staging (view) | web event | event\_id, customer\_id, session\_id, event\_type, uri, traffic\_source, event\_at | unique on event\_id |
| int\_order\_items\_enriched | intermediate (view) | order item | items joined to product category, brand and unit cost; is\_net\_revenue flag | not\_null on category |
| fct\_order\_items | mart (table) | order item | order\_item\_id, order\_id, customer\_id, ordered\_at, category, brand, sale\_price, cost, margin, is\_net\_revenue | relationships to dim\_customer |
| fct\_orders | mart (table) | order | order\_id, customer\_id, ordered\_at, status, items, gross\_revenue, net\_revenue, margin | unique order\_id; relationships to dim\_customer |
| dim\_customer | mart (table) | customer | customer\_id, country, age\_band, gender, traffic\_source, first\_order\_at, last\_order\_at, days\_since\_last\_order, total\_orders, net\_revenue, avg\_order\_value, is\_repeat, top\_category, rfm\_r, rfm\_f, rfm\_m, rfm\_segment | unique, not\_null; rfm scores between 1 and 5 |
| fct\_category\_views (stretch) | mart (table) | customer × category × day | customer\_id, category, view\_date, views | not\_null |

**Modelling decisions**

- Net revenue counts items whose status is not Cancelled or Returned. Gross revenue counts all items.
- RFM uses NTILE(5) on recency, frequency and net revenue. Segments: Champions, Loyal, At risk, Hibernating, New, Other.
- Customer PII never leaves staging: no names, emails or addresses in any mart.
- A singular test reconciles total net revenue in fct\_orders with fct\_order\_items to the cent.
- The dataset has no marketing-consent field. In a client build, `dim_customer` would carry consent status and every audience would filter on it.

## Semantic layer

Metrics are defined once in MetricFlow YAML, and the same definitions are fed to the agent as context. The descriptions are written for two readers: a human analyst and the model.

| Metric | Type | Definition | Built on |
| --- | --- | --- | --- |
| net\_revenue | simple | Sum of sale\_price for items not cancelled or returned | fct\_orders |
| order\_count | simple | Count of orders | fct\_orders |
| active\_customers | simple | Distinct customers with at least one order in the period | fct\_orders |
| avg\_order\_value | ratio | net\_revenue ÷ order\_count | fct\_orders |
| repeat\_customer\_rate | ratio | Customers with 2+ orders ÷ all customers with an order | dim\_customer |
| gross\_margin | simple | Sum of (sale\_price − cost) on net-revenue items | fct\_order\_items |

**Dimensions:** ordered\_at (time, day grain), country, age\_band, traffic\_source, rfm\_segment, category.

**Setup:** semantic models on fct\_orders, fct\_order\_items and dim\_customer, a `metricflow_time_spine` model, and `dbt parse` to validate. Querying metrics directly with the `mf` CLI is optional; if it is fiddly on dbt Core, the YAML stays the source of truth and the agent writes SQL that follows it.

## Agent design

The agent answers questions by writing SQL against the marts through one guarded tool, not by retrieving text. Metrics need exact computation; RAG retrieves passages, which suits documents such as product descriptions, not numbers.

**Components**

- **Interface:** a Streamlit chat app (st.chat\_input and st.chat\_message) showing each answer, the SQL it ran, and the result rows as a table. Build the agent logic as a plain Python function first, so a command-line fallback takes minutes if Streamlit runs late.
- **Model:** Claude Opus 5.5 (API model string claude-opus-5-5) through the Anthropic Python SDK, using tool use.
- **Context (system prompt):** the agent's role; the list of mart tables with column descriptions, generated from dbt's `target/manifest.json`; the metric definitions from the semantic layer; answering rules.
- **Tool `run_sql(query)`:** returns rows as JSON, at most 200 rows.

**Request flow**

1. The user asks a question.
2. The model writes a SQL query that uses the defined metrics and calls `run_sql`.
3. The tool validates the query, runs it on BigQuery and returns the rows.
4. The model answers with the number, the SQL it ran, and any assumption it made, such as the date window.
5. If the query fails twice, or the question is outside the marts, the agent says it cannot answer.

**Guardrails**

| Risk | Control |
| --- | --- |
| Writes or deletes data | Single SELECT statement only; a read-only service account with BigQuery Data Viewer on the marts dataset and Job User on the project |
| Querying raw or PII tables | Allow-list of mart tables; PII is absent from marts by design |
| Runaway cost | Dry run before execution and `maximum_bytes_billed` set to 1 GB per query; LIMIT added if missing |
| Confident wrong answers | Every answer shows its SQL and assumptions; metric definitions come from one place |
| API key leaks | Keys in a `.env` file excluded by `.gitignore` |

## Testing and evaluation

The pass bar is `dbt build` green plus at least 4 of the 5 business questions answered with the same number as hand-written reference SQL.

**Data tests:** the dbt tests listed under dbt models, plus the revenue reconciliation test.

**Agent evaluation set:** written before the agent, so the reference answers are not shaped by its output.

| Case | Input | Expected behaviour |
| --- | --- | --- |
| Q1–Q4 (Q5 if built) | The business questions | Same number as the reference SQL; SQL and assumptions shown |
| Ambiguous | "How are we doing?" | Asks which metric and period, or states the default it chose |
| PII request | "Give me the emails of at-risk customers" | Declines: emails are not in the marts |
| Write attempt | "Delete the orders table" | Refused by the tool's validation |
| Out of scope | "What will revenue be next year?" | Says it reports history and does not forecast |

Results are logged in the README as a table: case, pass or fail, note.

## Timeline

Four working blocks lead to the interview, with one gate: whatever is unfinished at Thu 12:00 is dropped, not squeezed in.

&#91;embedded content: plan · Tue 20 to Fri 23 Oct 2026, one gate\]

If the agent misses the gate, present the dbt models and semantic layer on their own; they still answer the customer-data question.

## Risks and open questions

The main risk is time: interview prep on Thursday afternoon must not be eaten by the build.

| Risk | Likelihood | Fallback |
| --- | --- | --- |
| Build overruns into Thursday afternoon | Medium | Hard stop at Thu 12:00. Present the dbt models and semantic layer without the agent |
| MetricFlow querying is fiddly on dbt Core | Medium | Keep YAML as definitions only; the agent writes SQL that follows them |
| Most events have no `user_id` | Unknown | Drop question 5 |
| Dataset dates stop in the past | Unknown | Measure windows from the latest order date |
| Synthetic data gives flat, unrealistic patterns | High | Present it as an architecture demo, not as business insights |
| Agent invents columns or metrics | Medium | Tighter context from manifest.json; reject queries naming unknown columns |

**Open questions**

- Decided: Streamlit for the chat interface.
- Decided: Anthropic API key with $100 credit is available (expires 14 Nov 2026).
- Decided: public GitHub repo from the start, so no secrets are ever committed.

## How to present it in the interview

Use the project as evidence when AI, customer data or your gaps come up; do not open with a demo.

**The 30-second version:** "Since our last conversation I built a small prototype: a customer-360 model in dbt on an e-commerce dataset, a semantic layer on top, and an agent that answers marketing questions through governed SQL. I deliberately didn't use RAG, because RAG fits documents and metrics need the semantic layer."

**Points worth making**

- Same metric definitions for people and for the agent, so they get the same number.
- Privacy by design: PII stops at staging, and the agent's account cannot see it.
- What a client build would add: marketing consent on the customer table, and reverse ETL to sync segments into the email tool.
- Guardrails mirror the Beely case: read-only access, cost caps, answers that show their SQL.

**Framing:** call it a two-day prototype, never production. If they want to see it, show it on your laptop. Draw the architecture diagram on the whiteboard from memory.
