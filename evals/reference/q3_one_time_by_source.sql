-- Q3: What share of customers bought only once, by acquisition traffic source?
-- Share = customers with exactly 1 order / customers with at least 1 order.
select
  traffic_source,
  countif(total_orders = 1) as one_time_customers,
  countif(total_orders > 0) as customers_with_orders,
  safe_divide(countif(total_orders = 1), countif(total_orders > 0)) as one_time_share
from `ecommerce-customer-360.c360_marts.dim_customer`
group by traffic_source
order by traffic_source
