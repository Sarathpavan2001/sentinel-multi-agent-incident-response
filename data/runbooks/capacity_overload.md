# Capacity Overload Runbook

## Symptoms
- Gradual latency increase correlated with traffic growth (not sudden spike)
- CPU utilization consistently above 80% across the fleet
- Auto-scaling group at or near maximum capacity
- Request queuing / connection pool exhaustion
- Load balancer 5xx errors increasing
- Traffic volume significantly above baseline (>1.5x normal)

## Diagnosis Steps
1. Compare current traffic to baseline: is this a predictable peak (event-driven) or unexpected?
2. Check auto-scaling status: has it triggered? Is it in cooldown? Has it reached max?
3. Review resource utilization: CPU, memory, network, disk I/O across all instances
4. Check for hot spots: is load evenly distributed or concentrated on specific instances?
5. Verify CDN is absorbing cacheable traffic: low cache hit rate compounds origin load
6. Check database connection pool: near-max connections indicate backend bottleneck
7. Look for concurrent events: World Cup streams, product launches, marketing campaigns

## Resolution
1. **Immediate**: Increase auto-scaling group max capacity
2. **If max capacity insufficient**: Enable traffic shedding (graceful degradation)
3. **For predictable peaks**: Pre-scale 30 minutes before expected peak
4. **CDN**: Purge and warm cache if hit rate is anomalously low
5. **Database**: Enable read replicas or connection pooling if DB is the bottleneck

## Escalation Criteria
- Auto-scaling at maximum and still insufficient
- Multiple regions affected simultaneously
- Traffic exceeds 3x baseline with no known event
- Database connection pool exhausted
