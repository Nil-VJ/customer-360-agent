-- One row per order item, joined to its product (category, brand) and inventory unit (cost).
-- Adds margin and the is_net_revenue flag used by every revenue metric.

with order_items as (

    select * from {{ ref('stg_order_items') }}

),

products as (

    select * from {{ ref('stg_products') }}

),

inventory_items as (

    select * from {{ ref('stg_inventory_items') }}

),

joined as (

    select
        order_items.order_item_id,
        order_items.order_id,
        order_items.customer_id,
        order_items.product_id,
        order_items.inventory_item_id,
        order_items.status,
        order_items.ordered_at,
        order_items.shipped_at,
        order_items.delivered_at,
        order_items.returned_at,
        products.category,
        products.brand,
        products.department,
        order_items.sale_price,
        inventory_items.cost

    from order_items
    left join products
        on order_items.product_id = products.product_id
    left join inventory_items
        on order_items.inventory_item_id = inventory_items.inventory_item_id

),

flagged as (

    select
        *,
        sale_price - cost                                   as margin,
        status in ('Complete', 'Shipped', 'Processing')     as is_net_revenue

    from joined

)

select * from flagged
