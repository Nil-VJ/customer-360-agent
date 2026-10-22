-- One row per order with item count and revenue totals rolled up from its items.

{{
    config(
        partition_by={'field': 'ordered_at', 'data_type': 'timestamp', 'granularity': 'month'},
        cluster_by=['customer_id']
    )
}}

with orders as (

    select * from {{ ref('stg_orders') }}

),

order_items as (

    select * from {{ ref('int_order_items_enriched') }}

),

item_totals as (

    select
        order_id,
        count(*)                                        as items,
        sum(sale_price)                                 as gross_revenue,
        sum(if(is_net_revenue, sale_price, 0))          as net_revenue,
        sum(if(is_net_revenue, margin, 0))              as margin

    from order_items
    group by order_id

),

final as (

    select
        orders.order_id,
        orders.customer_id,
        orders.ordered_at,
        orders.status,
        coalesce(item_totals.items, 0)                  as items,
        coalesce(item_totals.gross_revenue, 0)          as gross_revenue,
        coalesce(item_totals.net_revenue, 0)            as net_revenue,
        coalesce(item_totals.margin, 0)                 as margin

    from orders
    left join item_totals
        on orders.order_id = item_totals.order_id

)

select * from final
