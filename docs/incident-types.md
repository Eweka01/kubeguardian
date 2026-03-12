# V1 Incident Types

## 1. CrashLoopBackOff
- Trigger: pod restart count > 3 in 5 minutes
- Likely causes: bad env var, missing secret, app crash on startup
- Safe actions: restart deployment, rollback image

## 2. Failing readiness probe
- Trigger: pod not ready for > 2 minutes
- Likely causes: app not starting, wrong port, dependency unavailable
- Safe actions: restart deployment, scale replicas

## 3. High error rate
- Trigger: 5xx responses > 10% for 3 minutes
- Likely causes: downstream service down, config issue, bad deployment
- Safe actions: rollback image, scale replicas

# V1 Safe Remediation Actions
1. Restart deployment
2. Rollback to previous image
3. Scale replicas up
