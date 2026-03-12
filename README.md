# KubeGuardian AI
AI-assisted Kubernetes incident triage and remediation platform.

## Status
Phase 1 — Foundation complete ✓

## What's Been Built

### Phase 1 — Infrastructure (Complete)

| Step | Description | Status |
|------|-------------|--------|
| 1 | Tooling setup — AWS CLI, Terraform, kubectl, Helm | Done |
| 2 | Project scaffold + GitHub repo | Done |
| 3 | Incident types defined (CrashLoopBackOff, readiness probe, high error rate) | Done |
| 4 | VPC + EKS cluster via Terraform | Done |
| 5 | Kubernetes namespaces (app, monitoring, ops) | Done |

### Cluster Details
- **Cluster name:** kubeguardian
- **Region:** us-east-1
- **Kubernetes version:** 1.29
- **Nodes:** 2 × t3.medium (managed node group)
- **Endpoint:** https://40E4BCA9FB054A99FED0BF26E90CF7E3.gr7.us-east-1.eks.amazonaws.com
- **VPC CIDR:** 10.0.0.0/16 (2 private + 2 public subnets across 2 AZs)

### Namespaces
| Namespace | Purpose |
|-----------|---------|
| `app` | Microservices (api-gateway, payment-service, user-service) |
| `monitoring` | Prometheus, Grafana, Loki, Alertmanager |
| `ops` | Argo CD, internal tooling |

## Project Structure
```
kubeguardian/
├── infra/
│   ├── terraform/          # VPC + EKS cluster definitions
│   └── kubernetes/
│       └── namespaces/     # Namespace manifests
├── services/
│   ├── api-gateway/
│   ├── payment-service/
│   └── user-service/
├── agent/
│   ├── collector/          # Metric/log collection
│   ├── diagnosis/          # LLM diagnosis layer
│   └── executor/           # Safe remediation actions
├── runbooks/
└── docs/
    └── incident-types.md   # V1 incident types and safe actions
```

## Stack
- **Infrastructure:** AWS EKS, Terraform (modules v20/v5)
- **GitOps:** Argo CD
- **Observability:** Prometheus, Grafana, Loki, Alertmanager
- **Agent:** Python, LLM diagnosis layer
- **ChatOps:** Telegram, MCP server

## V1 Incident Types
Defined in [docs/incident-types.md](docs/incident-types.md):
1. **CrashLoopBackOff** — restart deployment, rollback image
2. **Failing readiness probe** — restart deployment, scale replicas
3. **High error rate (5xx > 10%)** — rollback image, scale replicas

## Next Steps
- [ ] Deploy 3 microservices (api-gateway, payment-service, user-service)
- [ ] Install Prometheus + Grafana stack
- [ ] Install Argo CD for GitOps
- [ ] Build Python collector agent
- [ ] Integrate LLM diagnosis layer
- [ ] Telegram ChatOps bot
