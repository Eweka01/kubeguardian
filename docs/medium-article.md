# I Built an AI-Powered Kubernetes Incident Response System — Here's How It Works

> When a pod crashes at 2 AM, KubeGuardian wakes up, diagnoses the problem with GPT-4o, texts you on Telegram, and fixes it the moment you approve — all without you touching a terminal.

---

## The Problem

On-call is broken.

A pod crashloops at 3 AM. Your phone goes off. You groggily open a terminal, run `kubectl get pods`, dig through logs, search Slack for the last time this happened, find the runbook, decide whether to restart or rollback, execute the fix, and write up the incident. Forty-five minutes later you go back to bed.

This happens dozens of times a week at companies running microservices on Kubernetes. The detection, diagnosis, and remediation steps are often the same — but they still require a human to do them manually every single time.

I wanted to change that. So I built **KubeGuardian** — an AI-driven incident response platform that detects, diagnoses, and fixes Kubernetes incidents automatically, with a human approval step before any change is made.

---

## What KubeGuardian Does

When a pod crashes or a service degrades:

1. **Prometheus** detects the incident and fires an alert
2. **n8n** receives the alert via webhook and orchestrates the response
3. The **FastAPI agent** collects evidence — pod logs, Kubernetes events, restart counts, deployment state
4. **GPT-4o** analyzes the evidence and returns a structured JSON diagnosis with root cause, confidence level, and recommended action
5. **Telegram** sends you a message with the full diagnosis and a one-click approval link
6. You tap **Approve** — n8n resumes and the agent executes the fix (rollback, restart, or scale)
7. Telegram confirms the fix is done
8. The incident is **logged to PostgreSQL** with MTTR calculated automatically
9. You can query the entire incident history from **Claude Desktop** in plain English

---

[SCREENSHOT: Architecture diagram — the full flow from Prometheus to Telegram to fix]

---

## The Stack

| Layer | Technology |
|---|---|
| Cloud | AWS EKS, ECR, VPC, Classic ELB |
| Infrastructure as Code | Terraform |
| Orchestration | Kubernetes 1.29 |
| Metrics | Prometheus + kube-state-metrics + node-exporter |
| Logs | Loki + Promtail |
| Dashboards | Grafana |
| Alerting | Alertmanager |
| Automation | n8n (self-hosted on EKS) |
| Agent API | FastAPI + Python Kubernetes SDK |
| AI Diagnosis | GPT-4o |
| ChatOps | Telegram Bot API |
| AI Interface | Claude Desktop + MCP Server (15 tools) |
| GitOps | Argo CD |
| Incident Database | PostgreSQL 15 |

Everything runs inside the Kubernetes cluster. Nothing is SaaS except the AI models and Telegram.

---

## Phase 1 — The Cluster

I provisioned the cluster using Terraform with the `terraform-aws-modules/eks` module. Three `t3.medium` nodes, Kubernetes 1.29, across two availability zones.

Three microservices simulate a real e-commerce backend:
- `api-gateway` — handles incoming requests
- `payment-service` — processes payments
- `user-service` — manages user accounts

Each service runs 2 replicas with readiness and liveness probes configured.

---

[SCREENSHOT: AWS EKS console — kubeguardian cluster Active]

---

[SCREENSHOT: kubectl get nodes — 3 nodes Ready]

---

[SCREENSHOT: kubectl get pods -n app — 6 pods Running]

---

## Phase 2 — Observability

A Kubernetes cluster without observability is a black box. I installed the full stack:

- **kube-prometheus-stack** (Prometheus + Alertmanager + node-exporter) via Helm
- **Loki + Promtail** for log aggregation
- **Grafana** with three dashboards: Node Exporter Full, Kubernetes Cluster Monitoring, and Kubernetes Pod Overview

All data sources — Prometheus and Loki — are wired directly from within the cluster. No external dependencies.

---

[SCREENSHOT: Grafana — Node Exporter Full dashboard showing live CPU and memory]

---

[SCREENSHOT: Grafana — Kubernetes Pods dashboard]

---

[SCREENSHOT: Prometheus Targets page — all scrape targets UP]

---

## Phase 3 — Alert Rules + Incident Simulator

I wrote three PrometheusRule alerts that match the most common real-world Kubernetes incidents:

```yaml
- alert: CrashLoopBackOff
  expr: rate(kube_pod_container_status_restarts_total[5m]) * 300 > 3
  for: 1m
  labels:
    severity: critical

- alert: PodNotReady
  expr: kube_pod_status_ready{condition="false"} == 1
  for: 2m
  labels:
    severity: warning

- alert: HighErrorRate
  expr: rate(http_requests_total{status=~"5.."}[3m]) /
        rate(http_requests_total[3m]) > 0.1
  for: 3m
  labels:
    severity: critical
```

I also built a bash simulator to trigger real incidents on demand — useful for demos and testing the full pipeline without waiting for real failures.

```bash
./scripts/simulate.sh crashloop payment-service
./scripts/simulate.sh readiness user-service
./scripts/simulate.sh errorrate api-gateway
./scripts/simulate.sh restore payment-service
```

---

[SCREENSHOT: Prometheus Alerts page — showing 3 alert rules]

---

[SCREENSHOT: Terminal — kubectl get pods -n app showing CrashLoopBackOff]

---

## Phase 4 — The FastAPI Agent

The agent is the brain of the remediation layer. It runs as a Kubernetes deployment in the `ops` namespace with a ClusterRole granting it read access across all namespaces and write access limited to safe operations.

Three core endpoints:

**Evidence collection:**
```
POST /evidence
→ Returns pods, events, restart counts, deployment state for a service
```

**Safe remediation (allow-listed, no arbitrary kubectl):**
```
POST /execute
→ type: rollout_restart | rollout_undo | scale
→ Executes via the Python Kubernetes SDK
```

**Incident logging:**
```
POST /incidents
→ Records service, incident type, root cause, action taken, outcome
→ MTTR is calculated automatically as a PostgreSQL generated column

GET /incidents/stats
→ Returns avg/min/max MTTR per service and incident type
```

The agent is containerized, pushed to Amazon ECR, and deployed via a Kubernetes manifest managed by Argo CD.

---

[SCREENSHOT: curl http://localhost:8000/health — {"status":"ok"}]

---

## Phase 5 — n8n Automation + Telegram ChatOps

This is where the pieces connect. n8n is a self-hosted workflow automation tool — think Zapier but running inside your cluster and fully programmable.

The workflow has 8 nodes:

```
Webhook → Collect Evidence → GPT-4o Diagnosis → Parse Response
→ Telegram Alert → Wait for Approval → Execute Fix → Telegram Confirm
```

The **Wait node** is the key to human-in-the-loop automation. n8n pauses the entire workflow and generates a unique `resumeUrl`. That URL goes into the Telegram message. When you tap it, n8n resumes exactly where it left off and calls the agent's `/execute` endpoint.

The Telegram alert looks like this:

```
🚨 KubeGuardian Alert

Service: payment-service
Root Cause: Container command override causing immediate exit
Confidence: high

Recommended Fix: rollout_undo

✅ Click to Approve Fix
```

One tap. The fix runs. Telegram confirms. Done.

---

[SCREENSHOT: n8n workflow canvas — all 8 nodes connected]

---

[SCREENSHOT: Telegram — alert message with approve link]

---

[SCREENSHOT: Telegram — "Fix Applied" confirmation message]

---

## Phase 6 — Claude Desktop + MCP Server

This is the part that surprised me most when I built it.

MCP (Model Context Protocol) lets you expose custom tools to Claude Desktop — so instead of opening a terminal, you just open a chat window and talk to your cluster in plain English.

I built a Node.js MCP server that exposes 15 tools:

| Tool | What it does |
|---|---|
| `cluster_health` | Full cluster overview — nodes, pods, any crashloops |
| `get_pods` | List pods in any namespace |
| `get_pod_logs` | Fetch recent logs from a pod |
| `collect_evidence` | Full incident evidence bundle |
| `rollout_restart` | Rolling restart — zero downtime |
| `rollout_undo` | Rollback to previous image |
| `scale_deployment` | Scale replicas up or down |
| `trigger_incident` | Simulate crashloop / readiness / errorrate |
| `restore_service` | Restore a service to healthy |
| `trigger_n8n_alert` | Manually fire the n8n pipeline |
| `list_n8n_executions` | List recent n8n workflow runs |
| `log_incident` | Log a resolved incident to PostgreSQL |
| `get_incident_stats` | Query MTTR stats by service |

In practice, the demo looks like this:

> *"Trigger a crashloop on payment-service"*
> *"Collect evidence for payment-service and tell me what's wrong"*
> *"Roll back payment-service to the previous image"*
> *"Log this incident — crashloop, root cause OOMKilled, action rollout_undo, outcome success"*
> *"Show me MTTR stats for payment-service"*

Claude handles the tool selection, argument mapping, and response formatting. You just talk.

---

[SCREENSHOT: Claude Desktop — hammer icon confirming MCP connected]

---

[SCREENSHOT: Claude Desktop — "Check cluster health" query and response]

---

[SCREENSHOT: Claude Desktop — "Collect evidence for payment-service" response showing diagnosis]

---

[SCREENSHOT: Claude Desktop — "Show me incident stats" showing MTTR data]

---

## Phase 7 — Argo CD GitOps

Every Kubernetes manifest in this project lives in `infra/kubernetes/` in the GitHub repo. Argo CD watches that directory and automatically applies any changes within ~3 minutes of a `git push`.

This means:
- Infrastructure changes are reviewed via pull requests, not `kubectl apply` in a terminal
- Manual cluster changes (`kubectl patch`) are automatically reverted to the committed state
- Every change is auditable in git history

---

[SCREENSHOT: Argo CD UI — kubeguardian app Synced + Healthy]

---

[SCREENSHOT: Argo CD — resource tree showing all deployments and services]

---

## Phase 8 — Incident Database + MTTR Tracking

Every resolved incident gets written to a PostgreSQL database with this schema:

```sql
CREATE TABLE incidents (
  id                SERIAL PRIMARY KEY,
  service           TEXT NOT NULL,
  incident_type     TEXT NOT NULL,
  root_cause        TEXT,
  confidence        TEXT,
  recommended_action TEXT,
  action_taken      TEXT NOT NULL,
  outcome           TEXT NOT NULL DEFAULT 'success',
  detected_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at       TIMESTAMPTZ,
  mttr_seconds      INTEGER GENERATED ALWAYS AS (
    EXTRACT(EPOCH FROM (resolved_at - detected_at))::INTEGER
  ) STORED
);
```

`mttr_seconds` is a PostgreSQL generated column — calculated automatically when `resolved_at` is set. No application code needed.

The `GET /incidents/stats` endpoint returns:

```
payment-service | crashloop | total=3 resolved=3 | avg_mttr=4min min=2min max=7min
user-service    | readiness | total=1 resolved=1 | avg_mttr=6min min=6min max=6min
```

---

[SCREENSHOT: Terminal — psql query showing incidents table with real rows]

---

[SCREENSHOT: Claude Desktop — "Show me incident stats for all services"]

---

## The Hardest Problems I Solved

Building this wasn't straightforward. Here are the real problems I hit and how I fixed them:

**EBS CSI driver on EKS 1.29**
EKS 1.29 deprecated the in-tree EBS provisioner. PVCs for n8n and PostgreSQL were stuck Pending until I installed the `aws-ebs-csi-driver` addon and attached `AmazonEBSCSIDriverPolicy` to the node role.

**n8n data loss on pod restart**
The original n8n deployment used `emptyDir` for storage. Every pod restart wiped the entire workflow database. I replaced it with a 5Gi EBS PersistentVolumeClaim. Also needed `securityContext.fsGroup: 1000` because n8n runs as UID 1000 but EBS volumes mount as root.

**AZ affinity for EBS volumes**
EBS volumes are locked to a single availability zone. When a PVC was created in `us-east-1a` but the only available node was in `us-east-1b`, the pod stayed Pending forever. Fixed by adding `nodeSelector: topology.kubernetes.io/zone: us-east-1b` to both postgres and n8n deployments.

**OpenAI Responses API format change**
The n8n OpenAI node updated to the new Responses API which returns `output[0].content[0].text` instead of `choices[0].message.content`. The Code node was silently failing and writing `undefined` to the database. Fixed by rewriting the parser to use optional chaining and check all three possible response formats.

**t3.medium pod limits**
A `t3.medium` node can only run 17 pods due to ENI limits. With the full observability stack running, the cluster was full. Fixed by scaling the node group from 2 to 3 nodes.

---

## What I'd Add in V3

- **TLS everywhere** — cert-manager + Let's Encrypt for n8n, Argo CD, and the agent API
- **Kubernetes Secrets** managed via AWS Secrets Manager or Vault instead of plaintext YAML
- **n8n auto-logging** — add a 9th node to the n8n workflow that calls `POST /incidents` after every fix
- **Grafana incident dashboard** — PostgreSQL data source in Grafana showing MTTR trends over time
- **Multi-service awareness** — n8n currently hardcodes `payment-service` as the target; dynamic service extraction from the alert payload would make it fully generic

---

## The GitHub Repo

Everything is open source. The README walks through all 8 phases with exact commands, from `terraform init` to a full demo run.

**GitHub:** https://github.com/Eweka01/kubeguardian

---

## Key Takeaways

If you're building something similar, here's what I'd tell you:

1. **Start with the alert → fix loop first.** Get Prometheus → Alertmanager → n8n → agent → fix working before adding AI, Telegram, or the database. Validate each step in isolation.

2. **EBS volumes have sharp edges on EKS.** AZ affinity, CSI drivers, and fsGroup are all things you won't hit in a local cluster. Budget time for them.

3. **n8n draft vs published is a real gotcha.** Workflows created via the API start as drafts. Webhooks only register for published workflows. Always toggle Active in the UI after creating or updating a workflow via API.

4. **MCP is underrated.** Adding Claude Desktop as a natural language interface to the cluster took less than 200 lines of JavaScript and completely changed how I interact with it. The value-to-effort ratio is exceptional.

5. **MTTR as a generated column is clean.** Letting PostgreSQL calculate `resolved_at - detected_at` in a generated column means your application never has to think about it.

---

*Built with AWS EKS, Terraform, Prometheus, Grafana, Loki, n8n, FastAPI, GPT-4o, Telegram, Argo CD, PostgreSQL, and Claude Desktop.*

*GitHub: https://github.com/Eweka01/kubeguardian*

---

**Tags:** #Kubernetes #DevOps #SRE #AI #MLOps #AWS #EKS #CloudNative #Automation #OpenAI #MCP #GitOps #ArgoCD #n8n #Prometheus #Grafana #Terraform #Python #FastAPI #Platform Engineering
