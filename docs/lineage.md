# Model lineage

Phase 1: raw source tables to staging views. Staging renames and casts columns and drops PII. No joins, no business logic.

```mermaid
flowchart LR
  subgraph src["bigquery-public-data.thelook_ecommerce"]
    users
    orders
    order_items
    inventory_items
    products
    events
  end

  subgraph stg["c360_staging (views)"]
    stg_users["stg_users<br/>PK customer_id · PII dropped"]
    stg_orders["stg_orders<br/>PK order_id · status checked"]
    stg_order_items["stg_order_items<br/>PK order_item_id · status checked"]
    stg_inventory_items["stg_inventory_items<br/>PK inventory_item_id"]
    stg_products["stg_products<br/>PK product_id"]
    stg_events["stg_events<br/>PK event_id · PII dropped"]
  end

  users --> stg_users
  orders --> stg_orders
  order_items --> stg_order_items
  inventory_items --> stg_inventory_items
  products --> stg_products
  events --> stg_events
```

Every staging key has `unique` and `not_null` tests. `status` in orders and order items must be one of
Cancelled, Complete, Processing, Returned, Shipped. Source freshness on `orders.created_at` warns after 36 hours.
