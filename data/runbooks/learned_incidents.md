# Learned Incidents — Auto-Generated Runbook Entries

## Incident INC-1F6E38E8

### Runbook: Handling Deployment-Induced Load Spikes

**Symptoms:**
- Sharp increase in 5xx errors.
- High CPU utilization ( > 80%) across cluster.
- Sudden drop in CDN cache hit rates (> 10% decrease).
- Correlation with recent deployment markers.

**Diagnosis Steps:**
1. Check Deployment Dashboard: Verify if a deployment occurred within the last 15 minutes.
2. Verify CDN Health: Check CloudFront/CDN metrics to confirm cache hit rate degradation.
3. Check Resource Metrics: Confirm if instance failure is tied to CPU exhaustion or OOM events.

**Resolution Steps:**
1. Confirm with the On-Call Engineer that a rollback is appropriate.
2. Execute rollback to the previous known stable version (e.g., v2.3.0).
3. Monitor CPU utilization and RPS to ensure stabilization.
4. Escalate to the deployment team for RCA if the rollback restores service.

*Note: All rollbacks in production require documented approval in the incident ticket.*

---

## Incident INC-65B4A29D

## Runbook: Handling Cascading Failure due to Deployment Regression

### Symptoms
- Spike in 5xx errors for video-streaming service.
- Unhealthy instance count > 10%.
- CDN cache hit rate < 80%.
- Database connection usage > 80%.

### Diagnosis
1. Check recent deployment logs: `kubectl get events -n video-streaming`.
2. Confirm if CDN cache efficiency dropped simultaneously with deployment.
3. Check if auto-scaling is struggling to spin up new instances.

### Resolution
1. **Rollback**: If symptoms correlate with a deployment, immediately revert to the previous known-good version (e.g., v2.3.0).
2. **Manual Intervention**: If instances remain unhealthy, manually restart instances to clear cache/local states.
3. **Scaling**: If auto-scaling fails, manually increase the minimum desired capacity to restore service baseline.
4. **Approval**: Requires Lead SRE or On-call Manager approval.

---

## Incident INC-BA45D9D6

## Runbook: Handling Deployment-Induced Origin Surge

### Symptoms
- Sudden drop in CDN cache hit rates.
- Unexpected spike in Origin RPS.
- Increased instance health check failures following a deployment.
- Database connection saturation.

### Diagnosis
1. Check recent deployments (Last 30 mins) via deployment logs.
2. Verify if CDN cache hit rates dropped simultaneously with the deployment.
3. Compare health check failure logs with the deployment timestamp.

### Resolution
1. If a direct correlation exists, immediately initiate a rollback to the previous stable image (deploy-4521).
2. Note: Rollback requires approval from the Incident Commander as it changes production state.
3. Monitor origin traffic and DB saturation post-rollback to verify recovery.

---

## Incident INC-27887F2A

## Runbook: Handling CDN Cache Hit Rate Drops and Origin Overload

### Symptoms
- Sharp decrease in CDN cache hit rate (e.g., >20% drop).
- Unexpected surge in Origin RPS.
- Elevated CPU utilization and DB connection saturation on origin instances.

### Diagnosis Steps
1. Check recent deployment logs: `kubectl get events -n video-streaming` or CI/CD audit logs.
2. Confirm if the issue correlates with a new version release.
3. Analyze dashboard for 'Cache Hit Ratio' vs 'Origin Request Rate'.
4. Verify instance health statuses.

### Resolution Steps
1. If a recent deployment occurred, trigger an immediate rollback via the deployment pipeline.
2. Verify the rollback completion: `kubectl rollout status deployment/video-streaming`.
3. Monitor origin RPS and Cache Hit Ratio to confirm return to baseline.
4. If the issue persists after rollback, investigate upstream network connectivity or CDN configuration errors.

---

## Incident INC-250A98DE

### Runbook: Handling Latency Degradation during Traffic Spikes

**Symptoms:**
- Latency degradation observed without a corresponding increase in CPU/Memory.
- CDN cache hit rate remains normal (>90%).
- Request volume shows a modest increase (5-15%).

**Diagnosis Steps:**
1. Confirm Origin health (check instance health count vs. active count).
2. Verify system metrics (CPU/Memory usage).
3. Check CDN logs to confirm traffic increase is organic.

**Resolution Steps:**
1. If infrastructure is healthy and CPU/Memory are stable, perform a manual scale-up of the Auto-Scaling Group (ASG) to reduce per-node load.
2. Increase desired capacity by 10-15% as a temporary measure.
3. Monitor latency improvement after the new instances reach 'InService' state.
4. Revert manual adjustments once traffic levels normalize.

---

## Incident INC-05BC82BC

# Runbook: Handling Origin Surge and Cache Efficiency Drops

## Symptoms
- CDN cache hit rate drops significantly (e.g., below 80%).
- Database connection pool saturation spikes (>80%).
- Unhealthy instance count increases in the video-streaming service.

## Diagnosis Steps
1. Check recent deployment logs via CI/CD dashboard for changes in connection handling or transcoding logic.
2. Verify if the 'origin surge' pattern is present by checking requests hitting the database vs. cache.
3. Identify affected instances using service health metrics.

## Resolution Steps
1. Confirm if a recent deployment occurred within the last 15 minutes.
2. If deployment v(n) correlates with the start of the symptoms, initiate an immediate rollback to version v(n-1).
3. Monitor connection pool saturation metrics during the rollback process.
4. Escalate to the Video Engineering team if stability is not restored within 5 minutes of rollback.

---

## Incident INC-FADBFCB6

### Runbook: Handling Latency Degradation via Auto-scaling Lag

**Symptoms:**
- Increased service latency (e.g., 80ms to 95ms).
- Traffic increase observed (even modest spikes, e.g., <10%).
- Infrastructure metrics (CPU/Memory) are stable and below exhaustion limits (<50%).

**Diagnosis:**
1. Confirm latency increase via service dashboard.
2. Verify resource metrics (CPU/Memory) to ensure no node saturation.
3. Check deployment history; if no rollout in last 2 hours, suspect scaling lag.
4. Refer to SOP INC-250A98DE for pattern matching.

**Resolution:**
1. Increase the ASG minimum instance count for the affected cluster by 20% to provide immediate overhead.
2. Adjust target CPU utilization threshold down (e.g., from 70% to 60%) to trigger scale-out events earlier.
3. Monitor latency dashboard to ensure return to nominal baseline.

---

## Incident INC-0E662D3C

## Runbook: Handling Deployment-Induced Performance Degradation

### Symptoms
- Sudden drop in CDN cache hit rates following a deployment.
- Immediate spike in latency and error rates.
- Rapid resource exhaustion (CPU/DB Connections) immediately post-deployment.

### Diagnosis Steps
1. Check the CI/CD pipeline for recent deployments in the affected region.
2. Compare pre-deployment and post-deployment metrics using the 'Deployment Impact' dashboard.
3. If correlation exists between the deployment time and the onset of errors, flag as a deployment regression.

### Resolution Steps
1. **Verify Regression**: Confirm the deployment version is the culprit by checking service logs for library initialization errors or connection timeouts.
2. **Rollback**: Execute a rollback to the previous known stable version (N-1) using the internal deployment tool.
3. **Monitor**: Observe CPU, DB connection, and Cache Hit Rate metrics for 10 minutes post-rollback.
4. **Escalate**: Tag the relevant development team for a post-deployment review if the rollback resolves the issue.

---

## Incident INC-6207B533

### Runbook: Latency Degradation via Auto-scaling Lag

**Symptoms:** 
- Increased response latency without corresponding saturation in CPU/Memory.
- Traffic spike detected (even if < 10%).

**Diagnosis Steps:**
1. Check CloudWatch metrics for request count vs. active instance count.
2. Verify if the ASG has recently scaled or is currently in a 'Cooldown' period.
3. Compare current latency against historical trends during minor spikes.

**Resolution Steps:**
1. Identify the relevant ASG: `video-streaming-asg-us-east-1`.
2. Navigate to Auto Scaling Group > Automatic Scaling.
3. Adjust the 'Cooldown' period. If traffic is volatile, reduce from 300s to 60s.
4. Monitor latency for 10 minutes to verify stabilization.

---

## Incident INC-E1D5000A

## Runbook: Addressing Latency Spikes in video-streaming (us-east-1)

### Symptoms
- Service latency increases (10-20% shift) while total CPU/Memory utilization remains below 50%.
- Traffic RPS shows a minor increase (<10%).

### Diagnosis
1. Confirm RPS spike using monitoring dashboard.
2. Verify if latency increase correlates with existing Auto-Scaling Group (ASG) scaling events.
3. Check if recent deployments occurred (if none, prioritize ASG lag).
4. Consult SOP INC-FADBFCB6 to confirm if current behavior matches known auto-scaling lag patterns.

### Resolution
1. If latency is sustained, increase the minimum desired capacity of the affected ASG by 15%.
2. Adjust the ASG target tracking policy CPU threshold from 75% to 60% to provide additional headroom.
3. Monitor latency for 30 minutes post-adjustment to ensure stabilization.

---

## Incident INC-154FC4AB

## Runbook: Handling Cascading Resource Exhaustion (Video-Streaming)

### Symptoms
- Spike in CPU utilization > 85%.
- Database connection pool saturation > 85%.
- Sudden drop in CDN cache hit rate.
- Fleet instances reporting 'Unhealthy' status.

### Diagnosis
1. Check recent deployments: `deployment-history --service video-streaming --region ap-south-1`.
2. Verify if resource spikes correlate with deployment timestamps.
3. Analyze logs for error patterns related to connection pools or transcoding tasks.

### Resolution Steps
1. If a recent deployment is identified as the source, initiate a rollback to the previous stable version (e.g., v2.3.0).
2. Execute: `rollback-deployment --id [DEPLOYMENT_ID] --version [PREVIOUS_VERSION]`.
3. Verify stability by monitoring CPU/Connection pool metrics post-rollback.
4. If traffic load is high, consider temporary rate limiting to allow the cluster to recover.

---

## Incident INC-974673FA

## Runbook: Handling High CPU/DB Saturation Post-Deployment

### Symptoms
- Sudden drop in CDN cache hit rate.
- Rapid spike in database connection saturation (>80%).
- High CPU utilization on origin instances.
- Instance health check failures following a recent deployment.

### Diagnosis
1. Check recent deployments: `get-deployment-history --region ap-south-1`.
2. Correlate start of errors with deployment timestamp.
3. Verify if new dependencies (e.g., libavcodec) or pool logic were introduced.
4. Check metrics: `monitoring-cli --metric db_saturation --service video-streaming`.

### Resolution
1. If a recent deployment exists, immediately revert to the previous known-stable version.
2. Execute: `rollback-deployment --version v2.3.0 --region ap-south-1`.
3. Verify health checks return to nominal status.
4. Escalate to the service engineering team to investigate the root cause of the regression.

---

## Incident INC-1D8A5395

## Runbook: Handling ASG Latency Spikes (Ref: INC-1D8A5395)

### Symptoms
- Increased service latency (e.g., +15-20%) during traffic increases.
- Infrastructure reports sufficient CPU/Memory headroom.
- Current instance count is significantly below the maximum provisioned capacity.

### Diagnosis Steps
1. Verify ASG 'Current Capacity' vs 'Desired Capacity' in the management console.
2. Check ASG 'Activity History' for pending or failed scaling events.
3. Compare 'Cooldown Period' against traffic fluctuation velocity.

### Resolution Steps
1. If scaling lag is confirmed: Reduce the ASG 'Cooldown Period' (e.g., from 300s to 60s).
2. If traffic is volatile: Increase the 'Minimum Capacity' of the ASG to provide a base buffer.
3. Validate that the new settings do not induce 'thrashing' (rapid scale-out/scale-in cycles).

---

## Incident INC-B08F4F4D

## Runbook: Handling Transcoding and Origin Load Degradation

### Symptoms
- Sudden drop in CDN cache hit rate (e.g., >10% decrease).
- Spikes in origin CPU and DB connection utilization without organic traffic growth.
- Increased 5xx errors or latency in video streaming delivery.

### Diagnosis Steps
1. Check the recent deployment history in the region using `kubectl rollout history` or internal CI/CD logs.
2. Confirm if the increase in origin RPS is due to cache bypass by comparing cache-hit-ratio metrics vs request volume.
3. Verify if DB connection counts are saturated using the monitoring dashboard.

### Resolution Steps
1. If a recent deployment occurred, perform an immediate rollback to the previous stable version.
2. Verify system recovery by observing the stabilization of the cache hit rate and origin CPU metrics.
3. Escalate to the Video Engineering team for root cause analysis of the transcoding pipeline.

---

