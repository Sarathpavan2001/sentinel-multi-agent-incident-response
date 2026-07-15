# Deployment Failure Runbook

## Symptoms
- Sudden spike in error rates immediately following a deployment
- Latency increase correlated with deploy timestamp (within 5-minute window)
- New error types appearing in logs that were not present before deployment
- Health check failures on recently deployed instances
- CDN cache hit rate drop (new code paths may bypass cache)

## Diagnosis Steps
1. Check deployment timeline: compare deploy timestamp against anomaly start time
2. Verify canary results: did the canary pass? Was it run in the same region?
3. Compare metrics before and after deployment: latency, error rate, resource usage
4. Check for dependency changes: new libraries, API version changes, config modifications
5. Review changeset size: large changesets (>30 files) have higher failure probability
6. Check connection pooling: new code may leak connections or change pool sizing
7. Verify database migration status: pending migrations can cause runtime errors

## Resolution
1. **Immediate**: Rollback to previous version if rollback is available
2. **If rollback unavailable**: Scale up healthy instances, route traffic away from affected instances
3. **Post-rollback**: Analyze the deployment diff to identify the breaking change
4. **Prevention**: Enforce staged rollouts with regional canaries before full deployment

## Escalation Criteria
- Rollback fails or is not available
- Multiple services affected simultaneously
- Error rate exceeds 20% after rollback
- Customer-facing impact duration exceeds 15 minutes
