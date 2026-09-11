select
    ordered_at as revenue_date,
    count(*) as order_count,
    sum(amount) as revenue
from {{ ref('stg_orders') }}
where status = 'complete'
group by 1
