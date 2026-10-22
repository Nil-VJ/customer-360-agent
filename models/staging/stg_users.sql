-- One row per customer. PII (names, email, address, coordinates) is dropped here and never reaches later layers.

with source as (

    select * from {{ source('thelook_ecommerce', 'users') }}

),

renamed as (

    select
        id                      as customer_id,
        age,
        gender,
        city,
        state,
        country,
        traffic_source,
        created_at              as signed_up_at

    from source

)

select * from renamed
