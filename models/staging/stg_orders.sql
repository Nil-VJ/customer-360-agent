-- One row per order.

with source as (

    select * from {{ source('thelook_ecommerce', 'orders') }}

),

renamed as (

    select
        order_id,
        user_id                 as customer_id,
        status,
        num_of_item             as item_count,
        created_at              as ordered_at,
        shipped_at,
        delivered_at,
        returned_at

    from source

)

select * from renamed
