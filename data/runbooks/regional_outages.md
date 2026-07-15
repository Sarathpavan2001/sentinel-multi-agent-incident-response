# Regional Outage Runbook

## Symptoms
- Service degradation isolated to a single geographic region
- Other regions show normal metrics
- Network-level issues: packet loss, routing anomalies, DNS resolution failures
- Infrastructure provider status page shows regional issues
- Multiple services in the same region affected simultaneously

## Diagnosis Steps
1. Confirm regional isolation: verify other regions are healthy
2. Check infrastructure provider status: AWS/GCP/Azure regional health dashboard
3. Review network metrics: packet loss, BGP route changes, DNS resolution times
4. Check if multiple services in the region are affected (suggests infra, not app issue)
5. Verify cross-region failover readiness: are standby regions healthy and scaled?
6. Check recent infrastructure changes: network ACL updates, security group modifications

## Resolution
1. **If provider outage**: Activate cross-region failover if available
2. **If network issue**: Contact provider support, activate backup network paths
3. **If partial**: Isolate unhealthy availability zones, redistribute to healthy AZs
4. **DNS failover**: Update DNS weights to route traffic to healthy regions
5. **Communication**: Notify affected customers with region-specific status updates

## Escalation Criteria
- Complete regional failure with no failover available
- Provider confirms extended outage (>1 hour estimated recovery)
- Cross-region failover target at capacity
- Data consistency concerns between regions
