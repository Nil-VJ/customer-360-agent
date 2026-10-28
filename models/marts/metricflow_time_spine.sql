-- One row per day, used by MetricFlow to group and fill metrics over time.
-- Starts at the first order date (7 Jan 2019) and runs one year past today.
with days as (
    select date_day
    from unnest(
        generate_date_array(date '2019-01-01', date_add(current_date(), interval 1 year))
    ) as date_day
)

select date_day from days
