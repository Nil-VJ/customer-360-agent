-- Q2: Which product categories bring the most revenue from repeat customers last quarter?
-- Last quarter = the previous full calendar quarter before today.
-- Repeat customer = dim_customer.is_repeat (2 or more lifetime orders).
-- Revenue = net revenue (items where is_net_revenue is true).
with repeat_items_last_quarter as (
  select
    items.category,
    items.sale_price
  from `ecommerce-customer-360.c360_marts.fct_order_items` as items
  inner join `ecommerce-customer-360.c360_marts.dim_customer` as customers
    on items.customer_id = customers.customer_id
  where customers.is_repeat
    and items.is_net_revenue
    and items.ordered_at >= timestamp(date_sub(date_trunc(current_date(), quarter), interval 1 quarter))
    and items.ordered_at < timestamp(date_trunc(current_date(), quarter))
)

select
  category,
  sum(sale_price) as net_revenue
from repeat_items_last_quarter
group by category
order by net_revenue desc
