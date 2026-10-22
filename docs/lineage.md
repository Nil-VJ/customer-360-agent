# Model lineage

Three layers. Staging views clean and rename and drop PII. The intermediate view holds the joins and the
net-revenue rule. Mart tables are the only objects the agent may query.

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

  subgraph int["c360_intermediate (view)"]
    int_order_items_enriched["int_order_items_enriched<br/>+ category, brand, cost, margin<br/>+ is_net_revenue flag"]
  end

  subgraph marts["c360_marts (tables) · read by the agent"]
    fct_order_items["fct_order_items<br/>partition ordered_at (month)<br/>cluster customer_id"]
    fct_orders["fct_orders<br/>items, gross/net revenue, margin<br/>partition ordered_at (month)<br/>cluster customer_id"]
    dim_customer["dim_customer<br/>age_band, order stats, RFM,<br/>top_category, is_repeat"]
  end

  users --> stg_users
  orders --> stg_orders
  order_items --> stg_order_items
  inventory_items --> stg_inventory_items
  products --> stg_products
  events --> stg_events

  stg_order_items --> int_order_items_enriched
  stg_products --> int_order_items_enriched
  stg_inventory_items --> int_order_items_enriched

  int_order_items_enriched --> fct_order_items
  int_order_items_enriched --> fct_orders
  stg_orders --> fct_orders
  stg_users --> dim_customer
  fct_orders --> dim_customer
  fct_order_items --> dim_customer
```

## Rules carried in the models

- Net revenue counts items with status Complete, Shipped or Processing. Cancelled and Returned are excluded.
- RFM scores are NTILE(5) over customers with at least one order; 5 is best on every axis.
- Customers who never ordered stay in `dim_customer` with zero orders, null RFM scores and segment Other.

## Tests

- `unique` and `not_null` on every staging key and every mart key.
- `accepted_values` on `status` in staging orders and order items.
- `relationships` from `fct_orders.customer_id` and `fct_order_items.customer_id` to `dim_customer`.
- Singular: RFM scores between 1 and 5 for every customer with an order.
- Singular: total net revenue in `fct_orders` equals `fct_order_items` within 0.01.
- Source freshness on `orders.created_at` warns after 36 hours.
