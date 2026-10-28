-- Q1: How many high-value customers have not bought in 90+ days?
-- High-value = rfm_m >= 4. Not bought in 90+ days = days_since_last_order >= 90.
select
  count(*) as customers
from `ecommerce-customer-360.c360_marts.dim_customer`
where rfm_m >= 4
  and days_since_last_order >= 90
