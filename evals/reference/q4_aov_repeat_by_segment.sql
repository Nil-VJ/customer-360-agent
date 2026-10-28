-- Q4: What are average order value and repeat rate by country and age band?
-- AOV = sum of net_revenue / count of orders (all statuses).
-- Repeat rate = customers with is_repeat true / customers with at least 1 order.
with order_stats as (
  select
    customers.country,
    customers.age_band,
    count(*) as orders,
    sum(orders.net_revenue) as net_revenue
  from `ecommerce-customer-360.c360_marts.fct_orders` as orders
  inner join `ecommerce-customer-360.c360_marts.dim_customer` as customers
    on orders.customer_id = customers.customer_id
  group by customers.country, customers.age_band
),

repeat_stats as (
  select
    country,
    age_band,
    countif(is_repeat) as repeat_customers,
    countif(total_orders > 0) as customers_with_orders
  from `ecommerce-customer-360.c360_marts.dim_customer`
  group by country, age_band
)

select
  order_stats.country,
  order_stats.age_band,
  safe_divide(order_stats.net_revenue, order_stats.orders) as avg_order_value,
  safe_divide(repeat_stats.repeat_customers, repeat_stats.customers_with_orders) as repeat_rate
from order_stats
inner join repeat_stats
  on order_stats.country = repeat_stats.country
  and order_stats.age_band = repeat_stats.age_band
order by order_stats.country, order_stats.age_band
