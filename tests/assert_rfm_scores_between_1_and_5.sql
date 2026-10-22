-- Every customer with at least one order must have RFM scores between 1 and 5.
-- Returns the offending rows; the test passes when it returns none.

select
    customer_id,
    total_orders,
    rfm_r,
    rfm_f,
    rfm_m

from {{ ref('dim_customer') }}
where total_orders > 0
  and (
        rfm_r is null or rfm_r not between 1 and 5
     or rfm_f is null or rfm_f not between 1 and 5
     or rfm_m is null or rfm_m not between 1 and 5
  )
