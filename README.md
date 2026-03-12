# KubeGuardian AI

AI-assisted Kubernetes incident triage and automated remediation platform. Detects real incidents on EKS, collects evidence, runs AI diagnosis, and executes safe fixes — all triggered from Telegram.

## Status

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Foundation — EKS cluster + microservices | Complete |
| Phase 2 | Observability — Prometheus, Grafana, Loki, Alertmanager | Complete |
| Phase 3 | Alert rules + incident simulator | Complete |
| Phase 4 | FastAPI agent — evidence collector + executor | Complete |
| Phase 5 | n8n automation + Telegram ChatOps | Complete |
| Phase 6 | MCP server | Upcoming |

---

## Architecture

```
                        ┌─────────────────────────────────────┐
                        │           AWS EKS Cluster           │
                        │                                     │
  Prometheus ──scrapes──▶  app namespace                     │
  Alertmanager ─fires──▶    ├── api-gateway    (2 pods)      │
  Loki ──────collects──▶    ├── payment-service (2 pods)     │
                        │    └── user-service   (2 pods)      │
                        │                                     │
                        │  ops namespace                      │
                        │    └── kubeguardian-agent (FastAPI) │
                        │                                     │
                        │  n8n namespace                      │
                        │    └── n8n (internet-facing ELB)   │
                        └─────────────────────────────────────┘
                                        │
                             Alertmanager webhook
                                        │
                                      n8n
                                        │
                          ┌─────────────────────────┐
                          │  1. Fetch evidence       │
                          │     (agent /evidence)    │
                          │  2. AI diagnosis         │
                          │     (Claude / GPT-4o)    │
                          │  3. Telegram message     │
                          │     with steps + fix     │
                          │  4. Wait for /approve    │
                          │  5. Execute fix          │
                          │     (agent /execute)     │
                          │  6. Confirm on Telegram  │
                          └─────────────────────────┘
```

---

## Phase 1 — Foundation

### What was built
- AWS EKS cluster provisioned with Terraform using official modules
- VPC with public and private subnets across 2 availability zones
- 3 Kubernetes namespaces: `app`, `monitoring`, `ops`
- 3 sample microservices deployed with health probes
- Incident types scoped and documented before any code was written

### Cluster
| Detail | Value |
|--------|-------|
| Cluster name | `kubeguardian` |
| Region | `us-east-1` |
| Kubernetes version | `1.29` |
| Nodes | 2 × `t3.medium` (managed node group, auto-scales 1–3) |
| VPC CIDR | `10.0.0.0/16` |
| Private subnets | `10.0.1.0/24`, `10.0.2.0/24` |
| Public subnets | `10.0.101.0/24`, `10.0.102.0/24` |
| NAT gateway | Single, in public subnet |

### Namespaces
| Namespace | Purpose |
|-----------|---------|
| `app` | Application microservices |
| `monitoring` | Prometheus, Grafana, Loki, Alertmanager |
| `ops` | KubeGuardian agent, internal tooling |

### Microservices (namespace: `app`)
All 3 services use `kennethreitz/httpbin` with liveness and readiness probes on `/status/200`.

| Service | Replicas | Port | Probe path |
|---------|----------|------|------------|
| `api-gateway` | 2 | 80 | `/status/200` |
| `payment-service` | 2 | 80 | `/status/200` |
| `user-service` | 2 | 80 | `/status/200` |

### V1 Incident Types
Defined in [docs/incident-types.md](docs/incident-types.md):

| Incident | Trigger | Safe Actions |
|----------|---------|--------------|
| CrashLoopBackOff | Pod restarts > 3 in 5 min | Restart deployment, rollback image |
| Failing readiness probe | Pod not ready > 2 min | Restart deployment, scale replicas |
| High error rate | 5xx responses > 10% for 3 min | Rollback image, scale replicas |

### Key files
- [infra/terraform/main.tf](infra/terraform/main.tf) — VPC + EKS cluster modules
- [infra/terraform/variables.tf](infra/terraform/variables.tf) — cluster config knobs
- [infra/kubernetes/namespaces/namespaces.yaml](infra/kubernetes/namespaces/namespaces.yaml)
- [infra/kubernetes/services/](infra/kubernetes/services/) — 3 service manifests

---

## Phase 2 — Observability Stack

### What was built
Full observability installed via Helm into the `monitoring` namespace:

| Component | Helm chart | Purpose |
|-----------|-----------|---------|
| Prometheus | `prometheus-community/kube-prometheus-stack` | Scrapes metrics from all pods and nodes |
| Alertmanager | bundled with kube-prometheus-stack | Fires alerts, routes to n8n webhook |
| Grafana | `grafana/grafana` | Dashboards — admin / `kubeguardian123` |
| Loki | `grafana/loki-stack` | Stores logs from all pods |
| Promtail | bundled with loki-stack | Ships pod logs into Loki (runs on every node) |

### Accessing the UIs (requires port-forward)
```bash
# Grafana — http://localhost:3000  (admin / kubeguardian123)
kubectl port-forward svc/grafana 3000:80 -n monitoring

# Prometheus — http://localhost:9090
kubectl port-forward svc/prometheus-kube-prometheus-prometheus 9090:9090 -n monitoring

# Alertmanager — http://localhost:9093
kubectl port-forward svc/prometheus-kube-prometheus-alertmanager 9093:9093 -n monitoring
```

### Grafana data sources to add manually
1. **Prometheus** → URL: `http://prometheus-kube-prometheus-prometheus:9090`
2. **Loki** → URL: `http://loki:3100`

### Key files
- [infra/helm/prometheus-values.yaml](infra/helm/prometheus-values.yaml)
- [infra/helm/loki-values.yaml](infra/helm/loki-values.yaml)
- [infra/helm/grafana-values.yaml](infra/helm/grafana-values.yaml)
- [infra/helm/install.sh](infra/helm/install.sh) — re-install script

---

## Phase 3 — Alert Rules + Incident Simulator

### What was built
- 3 `PrometheusRule` alert rules matching the V1 incident types
- Bash simulator to trigger real incidents on any service on demand

### Alert rules (namespace: `monitoring`)
Defined in [infra/kubernetes/monitoring/alert-rules.yaml](infra/kubernetes/monitoring/alert-rules.yaml):

| Alert | Expression | For | Severity |
|-------|-----------|-----|----------|
| `CrashLoopBackOff` | `increase(kube_pod_container_status_restarts_total[5m]) > 3` | 1m | critical |
| `PodNotReady` | `kube_pod_status_ready{condition="true"} == 0` | 2m | warning |
| `HighErrorRate` | `rate(promhttp_metric_handler_requests_total{code=~"5.."}[3m]) > 0.1` | 3m | critical |

Each alert carries `runbook` annotation listing the safe actions to apply.

### Incident simulator
[scripts/simulate.sh](scripts/simulate.sh) — break and restore any service on demand:

```bash
# Trigger incidents
./scripts/simulate.sh crashloop payment-service   # patches deployment to exit 1
./scripts/simulate.sh readiness user-service      # points readiness probe at /status/503
./scripts/simulate.sh errorrate api-gateway       # points both probes at /status/500

# Restore to healthy
./scripts/simulate.sh restore payment-service     # kubectl rollout undo

# Check current health
./scripts/simulate.sh status
```

---

## Phase 4 — FastAPI Agent (Evidence Collector + Executor)

### What was built
- Python FastAPI service containerised and pushed to Amazon ECR
- Deployed to the `ops` namespace with a dedicated ServiceAccount and RBAC
- ClusterRole grants read access to pods/logs/events and patch access to deployments
- Two endpoints: `/evidence` (gather) and `/execute` (act)

### API endpoints
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `POST` | `/evidence` | Collects pods, events, deployment state for a service |
| `POST` | `/execute` | Runs a safe remediation action from the allow-list |

### Allow-listed actions (hardcoded, no arbitrary kubectl)
| Action | kubectl command |
|--------|----------------|
| `rollout_restart` | `kubectl rollout restart deployment/<service>` |
| `rollout_undo` | `kubectl rollout undo deployment/<service>` |
| `scale` | `kubectl scale deployment/<service> --replicas=N` |

### ECR image
```
120430500058.dkr.ecr.us-east-1.amazonaws.com/kubeguardian-agent:latest
```

### Key files
- [agent/api.py](agent/api.py) — FastAPI app, routes, allow-list
- [agent/collector/gather.py](agent/collector/gather.py) — Kubernetes SDK evidence collection
- [agent/Dockerfile](agent/Dockerfile) — python:3.11-slim + kubectl binary
- [agent/requirements.txt](agent/requirements.txt)
- [infra/kubernetes/agent/deployment.yaml](infra/kubernetes/agent/deployment.yaml) — ServiceAccount, ClusterRole, Deployment, Service

---

## Phase 5 — n8n Automation + Telegram ChatOps

### What was built
- n8n deployed to EKS with an internet-facing Classic Load Balancer
- Alertmanager wired to post all alerts to n8n via webhook
- n8n workflow: alert → evidence → AI diagnosis → Telegram → human approval → execute fix → confirm

### n8n
| Detail | Value |
|--------|-------|
| URL | `http://a11cf5cd57696406db7e847bbc3f9fc8-509739064.us-east-1.elb.amazonaws.com:5678` |
| Login | `admin` / `kubeguardian123` |
| Namespace | `n8n` |

### n8n workflow (7 nodes)
```
Webhook trigger (POST /webhook/kubeguardian-alert)
  ↓
HTTP Request → agent /evidence
  ↓
AI Agent (Claude / GPT-4o) → structured JSON diagnosis
  ↓
Telegram → send summary + recommended fix + /approve_<id>
  ↓
Wait node → resume on /approve webhook
  ↓
HTTP Request → agent /execute
  ↓
Telegram → confirm fix applied
```

### Alertmanager config
[infra/kubernetes/monitoring/alertmanager-config.yaml](infra/kubernetes/monitoring/alertmanager-config.yaml) — routes all alerts to:
```
http://n8n.n8n.svc.cluster.local:5678/webhook/kubeguardian-alert
```

### Key files
- [infra/kubernetes/n8n/deployment.yaml](infra/kubernetes/n8n/deployment.yaml) — n8n Deployment + LoadBalancer Service
- [infra/kubernetes/monitoring/alertmanager-config.yaml](infra/kubernetes/monitoring/alertmanager-config.yaml)

---

## Full End-to-End Flow

```
1. ./scripts/simulate.sh crashloop payment-service
        ↓
2. payment-service pods enter CrashLoopBackOff
        ↓
3. Prometheus fires CrashLoopBackOff alert (after 1 min)
        ↓
4. Alertmanager POSTs to n8n webhook
        ↓
5. n8n calls agent /evidence → gathers pod state, events, restart counts
        ↓
6. n8n sends evidence to AI (Claude/GPT-4o)
        ↓
7. AI returns: root cause, confidence, steps, recommended_action
        ↓
8. Telegram message: summary + steps + /approve_<execution_id>
        ↓
9. SRE replies /approve_<id> in Telegram
        ↓
10. n8n resumes → calls agent /execute {type: "rollout_undo", service: "payment-service"}
        ↓
11. kubectl rollout undo restores previous image
        ↓
12. Telegram confirms: "Fix applied — payment-service restored"
```

---

## Project Structure

```
kubeguardian/
├── agent/
│   ├── api.py                  # FastAPI app — /health, /evidence, /execute
│   ├── Dockerfile              # python:3.11-slim + kubectl
│   ├── requirements.txt
│   └── collector/
│       └── gather.py           # Kubernetes SDK — pods, events, deployments
├── infra/
│   ├── helm/
│   │   ├── install.sh          # Full observability stack re-install
│   │   ├── prometheus-values.yaml
│   │   ├── loki-values.yaml
│   │   └── grafana-values.yaml
│   ├── kubernetes/
│   │   ├── agent/
│   │   │   └── deployment.yaml # ServiceAccount + RBAC + Deployment + Service
│   │   ├── monitoring/
│   │   │   ├── alert-rules.yaml        # 3 PrometheusRule alerts
│   │   │   └── alertmanager-config.yaml # Webhook → n8n
│   │   ├── n8n/
│   │   │   └── deployment.yaml # n8n + LoadBalancer
│   │   ├── namespaces/
│   │   │   └── namespaces.yaml
│   │   └── services/
│   │       ├── api-gateway.yaml
│   │       ├── payment-service.yaml
│   │       └── user-service.yaml
│   └── terraform/
│       ├── main.tf             # VPC + EKS modules
│       ├── variables.tf
│       ├── outputs.tf
│       └── versions.tf
├── scripts/
│   └── simulate.sh             # Incident simulator (crashloop/readiness/errorrate/restore)
└── docs/
    └── incident-types.md       # V1 incident types and safe actions
```

---

## Stack

| Layer | Technology |
|-------|-----------|
| Cloud | AWS (EKS, ECR, VPC, ELB) |
| Infrastructure as Code | Terraform (`terraform-aws-modules/eks` v20, `vpc` v5) |
| Container orchestration | Kubernetes 1.29 |
| Metrics | Prometheus + kube-state-metrics + node-exporter |
| Dashboards | Grafana |
| Logs | Loki + Promtail |
| Alerting | Alertmanager |
| Automation | n8n (self-hosted on EKS) |
| Agent API | FastAPI + Python Kubernetes SDK |
| AI diagnosis | Claude (Anthropic) or GPT-4o (OpenAI) |
| ChatOps | Telegram Bot API |
| Package management | Helm v4 |

---

## Quick Reference Commands

```bash
# Cluster
kubectl get nodes
kubectl get pods -n app
kubectl get pods -n monitoring
kubectl get pods -n ops

# Simulate incidents
./scripts/simulate.sh crashloop payment-service
./scripts/simulate.sh readiness user-service
./scripts/simulate.sh errorrate api-gateway
./scripts/simulate.sh restore payment-service

# Port-forward UIs
kubectl port-forward svc/grafana 3000:80 -n monitoring
kubectl port-forward svc/prometheus-kube-prometheus-prometheus 9090:9090 -n monitoring
kubectl port-forward svc/kubeguardian-agent 8000:8000 -n ops

# Agent API (while port-forwarded)
curl http://localhost:8000/health
curl -X POST http://localhost:8000/evidence \
  -H "Content-Type: application/json" \
  -d '{"service":"payment-service","namespace":"app"}'

# n8n (no port-forward needed — public LoadBalancer)
# http://a11cf5cd57696406db7e847bbc3f9fc8-509739064.us-east-1.elb.amazonaws.com:5678
```
