-- One row per item sold. Partitioned by month of ordered_at and clustered by customer_id so that
-- agent queries filtered on date or customer scan less data.

{{
    config(
        partition_by={'field': 'ordered_at', 'data_type': 'timestamp', 'granularity': 'month'},
        cluster_by=['customer_id']
    )
}}

with order_items as (

    select * from {{ ref('int_order_items_enriched') }}

),

final as (

    select
        order_item_id,
        order_id,
        customer_id,
        ordered_at,
        status,
        category,
        brand,
        sale_price,
        cost,
        margin,
        is_net_revenue

    from order_items

)

select * from final
