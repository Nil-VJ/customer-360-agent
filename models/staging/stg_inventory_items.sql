-- One row per physical unit in stock. The source repeats product attributes on every row;
-- those are dropped here so category, brand and price come only from stg_products.

with source as (

    select * from {{ source('thelook_ecommerce', 'inventory_items') }}

),

renamed as (

    select
        id                      as inventory_item_id,
        product_id,
        cast(cost as numeric)   as cost,
        created_at              as stocked_at,
        sold_at

    from source

)

select * from renamed
