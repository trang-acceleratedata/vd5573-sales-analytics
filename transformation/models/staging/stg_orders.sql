select
    order_id,
    customer_id,
    cast(ordered_at as date) as ordered_at,
    cast(amount as decimal(18, 2)) as amount,
    status
from {{ ref('raw_orders') }}
