-- One row per web event. ip_address and postal_code are dropped as personal data.
-- About 46% of events have no customer_id (anonymous sessions).

with source as (

    select * from {{ source('thelook_ecommerce', 'events') }}

),

renamed as (

    select
        id                      as event_id,
        user_id                 as customer_id,
        session_id,
        sequence_number,
        event_type,
        uri,
        traffic_source,
        browser,
        city,
        state,
        created_at              as event_at

    from source

)

select * from renamed
