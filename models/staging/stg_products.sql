-- One row per product.

with source as (

    select * from {{ source('thelook_ecommerce', 'products') }}

),

renamed as (

    select
        id                              as product_id,
        name                            as product_name,
        category,
        brand,
        department,
        sku,
        cast(cost as numeric)           as cost,
        cast(retail_price as numeric)   as retail_price,
        distribution_center_id

    from source

)

select * from renamed
