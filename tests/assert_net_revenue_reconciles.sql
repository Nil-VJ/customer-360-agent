-- Total net revenue in fct_orders must equal total net revenue in fct_order_items (tolerance 0.01).

with orders_total as (

    select sum(net_revenue) as net_revenue
    from {{ ref('fct_orders') }}

),

items_total as (

    select sum(if(is_net_revenue, sale_price, 0)) as net_revenue
    from {{ ref('fct_order_items') }}

)

select
    orders_total.net_revenue    as orders_net_revenue,
    items_total.net_revenue     as items_net_revenue

from orders_total
cross join items_total
where abs(orders_total.net_revenue - items_total.net_revenue) > 0.01
