-- One row per customer: profile, order history, RFM scores and segment.
-- Customers who never ordered keep their profile; order metrics are 0 and RFM scores are null.

with customers as (

    select * from {{ ref('stg_users') }}

),

orders as (

    select * from {{ ref('fct_orders') }}

),

order_items as (

    select * from {{ ref('fct_order_items') }}

),

order_stats as (

    select
        customer_id,
        min(ordered_at)                                 as first_order_at,
        max(ordered_at)                                 as last_order_at,
        count(*)                                        as total_orders,
        sum(net_revenue)                                as net_revenue

    from orders
    group by customer_id

),

category_revenue as (

    select
        customer_id,
        category,
        sum(sale_price)                                 as category_net_revenue

    from order_items
    where is_net_revenue
    group by customer_id, category

),

top_category as (

    select
        customer_id,
        category                                        as top_category

    from category_revenue
    qualify row_number() over (
        partition by customer_id
        order by category_net_revenue desc, category
    ) = 1

),

rfm_scores as (

    -- NTILE(5) over all customers with at least one order. 5 is best on every axis.
    -- customer_id breaks ties so the result is deterministic.
    select
        customer_id,
        ntile(5) over (order by last_order_at, customer_id)   as rfm_r,
        ntile(5) over (order by total_orders, customer_id)    as rfm_f,
        ntile(5) over (order by net_revenue, customer_id)     as rfm_m

    from order_stats

),

final as (

    select
        customers.customer_id,
        customers.country,
        case
            when customers.age < 18 then 'Under 18'
            when customers.age <= 24 then '18-24'
            when customers.age <= 34 then '25-34'
            when customers.age <= 44 then '35-44'
            when customers.age <= 54 then '45-54'
            when customers.age <= 64 then '55-64'
            else '65+'
        end                                                     as age_band,
        customers.gender,
        customers.traffic_source,
        customers.signed_up_at,
        order_stats.first_order_at,
        order_stats.last_order_at,
        date_diff(current_date(), date(order_stats.last_order_at), day)
                                                                as days_since_last_order,
        coalesce(order_stats.total_orders, 0)                   as total_orders,
        coalesce(order_stats.net_revenue, 0)                    as net_revenue,
        safe_divide(order_stats.net_revenue, order_stats.total_orders)
                                                                as avg_order_value,
        coalesce(order_stats.total_orders, 0) >= 2              as is_repeat,
        top_category.top_category,
        rfm_scores.rfm_r,
        rfm_scores.rfm_f,
        rfm_scores.rfm_m,
        case
            when rfm_scores.rfm_r >= 4 and rfm_scores.rfm_f >= 4 and rfm_scores.rfm_m >= 4 then 'Champions'
            when rfm_scores.rfm_f >= 4 then 'Loyal'
            when rfm_scores.rfm_r = 5 and rfm_scores.rfm_f <= 2 then 'New'
            when rfm_scores.rfm_r <= 2 and (rfm_scores.rfm_f >= 3 or rfm_scores.rfm_m >= 3) then 'At risk'
            when rfm_scores.rfm_r <= 2 then 'Hibernating'
            else 'Other'
        end                                                     as rfm_segment

    from customers
    left join order_stats
        on customers.customer_id = order_stats.customer_id
    left join top_category
        on customers.customer_id = top_category.customer_id
    left join rfm_scores
        on customers.customer_id = rfm_scores.customer_id

)

select * from final
