# KubeGuardian AI

> AI-assisted Kubernetes incident triage and automated remediation platform. Detects real incidents on EKS, collects evidence, runs AI diagnosis, executes safe fixes, logs every incident to a database, and tracks MTTR — all queryable from Claude Desktop via natural language.

---
Screen Recording 2026-03-13 at 12.51.06 AM.mov

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Tech Stack](#tech-stack)
4. [Prerequisites](#prerequisites)
5. [Phase 1 — EKS Cluster + Microservices](#phase-1--eks-cluster--microservices)
6. [Phase 2 — Observability Stack](#phase-2--observability-stack)
7. [Phase 3 — Alert Rules + Incident Simulator](#phase-3--alert-rules--incident-simulator)
8. [Phase 4 — FastAPI Agent](#phase-4--fastapi-agent)
9. [Phase 5 — n8n Automation + Telegram ChatOps](#phase-5--n8n-automation--telegram-chatops)
10. [Phase 6 — MCP Server (Claude Desktop)](#phase-6--mcp-server-claude-desktop)
11. [Phase 7 — Argo CD GitOps](#phase-7--argo-cd-gitops)
12. [Phase 8 — Incident Database + MTTR Tracking (V2)](#phase-8--incident-database--mttr-tracking-v2)
13. [Claude Desktop — Example Queries](#claude-desktop--example-queries)
14. [End-to-End Demo](#end-to-end-demo)
15. [Project Structure](#project-structure)
16. [Quick Reference](#quick-reference)

---

## Overview

KubeGuardian is a full AI-driven incident response platform built on AWS EKS. When a pod crashes or a service degrades, the platform:

1. Detects the incident via Prometheus alerting
2. Collects evidence automatically (pod logs, events, restart counts, deployment state)
3. Sends evidence to an AI model (GPT-4o or Claude) for root cause analysis
4. Notifies an SRE on Telegram with a diagnosis and recommended fix
5. Waits for human approval
6. Executes the fix (rollback, restart, or scale)
7. Confirms the remediation on Telegram
8. Logs the incident to PostgreSQL with MTTR calculated automatically
9. Exposes 15 MCP tools to Claude Desktop for natural language cluster control and incident history queries

The entire stack runs on Kubernetes and is managed via GitOps with Argo CD.

---

## Architecture

```
                        ┌──────────────────────────────────────────────┐
                        │               AWS EKS Cluster                │
                        │                                              │
  Prometheus ──scrapes──▶  app namespace                              │
  Alertmanager ─fires──▶    ├── api-gateway      (2 pods)            │
  Loki ──────collects──▶    ├── payment-service  (2 pods)            │
                        │    └── user-service    (2 pods)             │
                        │                                              │
                        │  ops namespace                               │
                        │    ├── kubeguardian-agent  (FastAPI)         │
                        │    └── postgres            (incident DB)     │
                        │                                              │
                        │  n8n namespace                               │
                        │    └── n8n  (internet-facing ELB)           │
                        │                                              │
                        │  argocd namespace                            │
                        │    └── argocd-server  (GitOps)              │
                        └──────────────────────────────────────────────┘
                                          │
                               Alertmanager webhook
                                          │
                                        n8n
                                          │
                            ┌─────────────────────────┐
                            │  1. Fetch evidence       │
                            │     (agent /evidence)    │
                            │  2. AI diagnosis         │
                            │     (GPT-4o / Claude)    │
                            │  3. Telegram message     │
                            │     with steps + fix     │
                            │  4. Wait for /approve    │
                            │  5. Execute fix          │
                            │     (agent /execute)     │
                            │  6. Confirm on Telegram  │
                            └─────────────────────────┘
                                          │
                            Claude Desktop (MCP Server)
                            ← 15 tools — natural language →
                            ← query cluster + incident DB →
```

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Cloud | AWS (EKS, ECR, VPC, Classic ELB) |
| Infrastructure as Code | Terraform (`terraform-aws-modules/eks` v20, `vpc` v5) |
| Container orchestration | Kubernetes 1.29 |
| Metrics | Prometheus + kube-state-metrics + node-exporter |
| Dashboards | Grafana (Node Exporter Full, K8s Cluster, K8s Pods) |
| Logs | Loki + Promtail |
| Alerting | Alertmanager |
| Automation | n8n (self-hosted on EKS, EBS-backed) |
| Agent API | FastAPI + Python Kubernetes SDK |
| Incident database | PostgreSQL 15 (EBS-backed, ops namespace) |
| AI diagnosis | GPT-4o (OpenAI) or Claude (Anthropic) |
| ChatOps | Telegram Bot API |
| MCP integration | Model Context Protocol server (Node.js) — 15 tools |
| GitOps | Argo CD |
| Package management | Helm v4 |

---

## Prerequisites

Install the following tools before starting. Every command in this guide assumes they are on your `PATH`.

### Required CLI tools

| Tool | Version | Install |
|------|---------|---------|
| AWS CLI | v2 | https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html |
| Terraform | >= 1.5 | https://developer.hashicorp.com/terraform/install |
| kubectl | >= 1.29 | https://kubernetes.io/docs/tasks/tools/ |
| Helm | v4 | https://helm.sh/docs/intro/install/ |
| Docker | latest | https://docs.docker.com/get-docker/ |
| Node.js | >= 18 | https://nodejs.org/ |
| git | any | https://git-scm.com/ |

### AWS account setup

You need an AWS account with a non-root IAM user that has sufficient permissions.

```bash
# Configure AWS credentials
aws configure
# AWS Access Key ID: <your-key>
# AWS Secret Access Key: <your-secret>
# Default region: us-east-1
# Default output format: json

# Verify
aws sts get-caller-identity
```

The IAM user needs the following AWS managed policies (or equivalent):
- `AmazonEKSClusterPolicy`
- `AmazonEKSWorkerNodePolicy`
- `AmazonEC2ContainerRegistryFullAccess`
- `AmazonVPCFullAccess`
- `IAMFullAccess`
- `AmazonEC2FullAccess`

### External accounts you will need

| Service | Purpose | Sign up |
|---------|---------|---------|
| OpenAI | AI diagnosis in n8n workflow | https://platform.openai.com |
| Telegram | ChatOps notifications + approvals | https://telegram.org |
| GitHub | GitOps repo for Argo CD | https://github.com |

### Clone the repository

```bash
git clone https://github.com/Eweka01/kubeguardian.git
cd kubeguardian
```

---

## Phase 1 — EKS Cluster + Microservices

### What this phase builds
- VPC with public + private subnets across 2 availability zones
- EKS cluster (Kubernetes 1.29) with a managed node group (2–3 × `t3.medium`)
- 3 namespaces: `app`, `monitoring`, `ops`
- 3 sample microservices with health probes

### 1.1 Provision the cluster with Terraform

```bash
cd infra/terraform

# Download providers
terraform init

# Review the plan — no changes are applied yet
terraform plan

# Provision VPC + EKS (~12 minutes)
terraform apply
```

When complete, Terraform outputs the cluster name and endpoint.

### 1.2 Configure kubectl

```bash
aws eks update-kubeconfig --region us-east-1 --name kubeguardian

# Verify connectivity
kubectl get nodes
```

If you see `Error: server has asked for the client to provide credentials`, your IAM user is not mapped to the cluster. Run:

```bash
# Replace <your-iam-arn> with the output of: aws sts get-caller-identity --query Arn --output text
aws eks create-access-entry \
  --cluster-name kubeguardian \
  --principal-arn <your-iam-arn> \
  --region us-east-1

aws eks associate-access-policy \
  --cluster-name kubeguardian \
  --principal-arn <your-iam-arn> \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy \
  --access-scope type=cluster \
  --region us-east-1
```

### 1.3 Tag public subnets for Classic ELB

Required for LoadBalancer services (n8n, Argo CD) to receive public IPs:

```bash
# Get your public subnet IDs
aws ec2 describe-subnets \
  --filters "Name=tag:Name,Values=kubeguardian-vpc-public*" \
  --query "Subnets[*].SubnetId" \
  --output text

# Tag each public subnet
aws ec2 create-tags \
  --resources <subnet-id-1> <subnet-id-2> \
  --tags Key=kubernetes.io/role/elb,Value=1
```

### 1.4 Create namespaces and deploy microservices

```bash
# Create namespaces
kubectl apply -f infra/kubernetes/namespaces/namespaces.yaml

# Deploy the 3 microservices
kubectl apply -f infra/kubernetes/services/

# Verify — all pods should reach Running within 60 seconds
kubectl get pods -n app
```

Expected output:
```
NAME                               READY   STATUS    RESTARTS   AGE
api-gateway-xxx                    1/1     Running   0          30s
api-gateway-xxx                    1/1     Running   0          30s
payment-service-xxx                1/1     Running   0          30s
payment-service-xxx                1/1     Running   0          30s
user-service-xxx                   1/1     Running   0          30s
user-service-xxx                   1/1     Running   0          30s
```

### Cluster details

| Detail | Value |
|--------|-------|
| Cluster name | `kubeguardian` |
| Region | `us-east-1` |
| Kubernetes version | `1.29` |
| Nodes | 2–3 × `t3.medium` (auto-scales 1–3) |
| VPC CIDR | `10.0.0.0/16` |
| Private subnets | `10.0.1.0/24`, `10.0.2.0/24` |
| Public subnets | `10.0.101.0/24`, `10.0.102.0/24` |

---

## Phase 2 — Observability Stack

### What this phase builds
- Prometheus — scrapes metrics from all pods and nodes
- Alertmanager — fires alerts, routes to n8n webhook
- Grafana — dashboards (Node Exporter Full, Kubernetes Cluster, Kubernetes Pods)
- Loki + Promtail — log aggregation

### 2.1 Add Helm repositories

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
```

### 2.2 Install the full observability stack

```bash
# Install kube-prometheus-stack (Prometheus + Alertmanager + node-exporter)
helm install prometheus prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f infra/helm/prometheus-values.yaml

# Install Loki + Promtail (log storage + collector)
helm install loki grafana/loki-stack \
  -n monitoring \
  -f infra/helm/loki-values.yaml

# Install Grafana
helm install grafana grafana/grafana \
  -n monitoring \
  -f infra/helm/grafana-values.yaml
```

To re-install everything at once:

```bash
bash infra/helm/install.sh
```

### 2.3 Verify pods

```bash
kubectl get pods -n monitoring
```

All pods should be `Running` within 2–3 minutes.

### 2.4 Access the UIs (port-forward required)

```bash
# Grafana — http://localhost:3000  (admin / kubeguardian123)
kubectl port-forward svc/grafana 3000:80 -n monitoring

# Prometheus — http://localhost:9090
kubectl port-forward svc/prometheus-kube-prometheus-prometheus 9090:9090 -n monitoring

# Alertmanager — http://localhost:9093
kubectl port-forward svc/prometheus-kube-prometheus-alertmanager 9093:9093 -n monitoring
```

### 2.5 Add data sources in Grafana

Open http://localhost:3000 → Connections → Data Sources → Add:

1. **Prometheus** — URL: `http://prometheus-kube-prometheus-prometheus:9090`
2. **Loki** — URL: `http://loki:3100`

### 2.6 Import dashboards

In Grafana → Dashboards → Import, paste these IDs one at a time:

| Dashboard | Grafana ID |
|-----------|-----------|
| Node Exporter Full | `1860` |
| Kubernetes Cluster Monitoring | `7249` |
| Kubernetes Pod Overview | `19792` |

---

## Phase 3 — Alert Rules + Incident Simulator

### What this phase builds
- 3 PrometheusRule alerts matching real incident patterns
- Bash simulator to trigger real incidents on demand

### 3.1 Apply alert rules

```bash
kubectl apply -f infra/kubernetes/monitoring/alert-rules.yaml
```

The 3 alerts:

| Alert | Trigger condition | For | Severity |
|-------|------------------|-----|----------|
| `CrashLoopBackOff` | Pod restarts > 3 in 5 min | 1m | critical |
| `PodNotReady` | Pod not ready | 2m | warning |
| `HighErrorRate` | 5xx rate > 10% for 3 min | 3m | critical |

Each alert includes a `runbook` annotation with the safe actions to apply.

### 3.2 Test the incident simulator

```bash
# Make the script executable
chmod +x scripts/simulate.sh

# Trigger a CrashLoopBackOff on payment-service
./scripts/simulate.sh crashloop payment-service

# Watch pods enter crash loop
kubectl get pods -n app -w

# Trigger a failing readiness probe on user-service
./scripts/simulate.sh readiness user-service

# Trigger high error rate on api-gateway
./scripts/simulate.sh errorrate api-gateway

# Restore any service to healthy
./scripts/simulate.sh restore payment-service

# View current health of all services
./scripts/simulate.sh status
```

---

## Phase 4 — FastAPI Agent

### What this phase builds
- Python FastAPI service with endpoints for evidence collection, remediation, and incident logging
- Containerised and pushed to Amazon ECR
- Deployed to the `ops` namespace with RBAC least-privilege access

### 4.1 Create an ECR repository

```bash
# Replace 123456789012 with your AWS account ID
aws ecr create-repository \
  --repository-name kubeguardian-agent \
  --region us-east-1
```

### 4.2 Build and push the Docker image

```bash
cd agent

# Authenticate Docker to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  <your-account-id>.dkr.ecr.us-east-1.amazonaws.com

# Build for linux/amd64 (required for EKS nodes)
docker buildx build --platform linux/amd64 \
  -t <your-account-id>.dkr.ecr.us-east-1.amazonaws.com/kubeguardian-agent:latest \
  --push .

cd ..
```

### 4.3 Update the deployment manifest

Edit [infra/kubernetes/agent/deployment.yaml](infra/kubernetes/agent/deployment.yaml) and replace the image with your ECR URI:

```yaml
image: <your-account-id>.dkr.ecr.us-east-1.amazonaws.com/kubeguardian-agent:latest
```

### 4.4 Grant EKS nodes ECR pull access

```bash
# Get the node group role name
aws eks describe-nodegroup \
  --cluster-name kubeguardian \
  --nodegroup-name default \
  --query "nodegroup.nodeRole" \
  --output text

# Attach ECR read policy to the node role
aws iam attach-role-policy \
  --role-name <node-role-name> \
  --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly
```

### 4.5 Deploy the agent

```bash
kubectl apply -f infra/kubernetes/agent/deployment.yaml

# Watch it come up
kubectl get pods -n ops -w
```

### 4.6 Test the agent API

```bash
# Port-forward to the agent
kubectl port-forward svc/kubeguardian-agent 8000:8000 -n ops

# Health check
curl http://localhost:8000/health

# Collect evidence for payment-service
curl -X POST http://localhost:8000/evidence \
  -H "Content-Type: application/json" \
  -d '{"service": "payment-service", "namespace": "app"}'

# Execute a rollout restart
curl -X POST http://localhost:8000/execute \
  -H "Content-Type: application/json" \
  -d '{"type": "rollout_restart", "service": "payment-service", "namespace": "app"}'
```

### Agent endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/evidence` | POST | Collect pods, events, logs, restart counts |
| `/execute` | POST | Execute `rollout_restart`, `rollout_undo`, or `scale` |
| `/incidents` | POST | Log a resolved incident to PostgreSQL |
| `/incidents/stats` | GET | Query MTTR statistics per service |

---

## Phase 5 — n8n Automation + Telegram ChatOps

### What this phase builds
- n8n workflow automation engine deployed on EKS with a persistent EBS volume and public LoadBalancer
- Alertmanager configured to POST all alerts to n8n
- 8-node n8n workflow: alert → evidence → AI diagnosis → Telegram → approval → fix → confirm
- Telegram bot for ChatOps notifications and human-in-the-loop approvals

### 5.1 Create a Telegram bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the bot token: `1234567890:AAXXXXXXXXXXXXXXXX`
4. Start a conversation with your new bot, then get your chat ID:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates"
# Look for "chat":{"id": <YOUR_CHAT_ID>}
```

### 5.2 Deploy n8n to EKS

```bash
kubectl apply -f infra/kubernetes/n8n/deployment.yaml

# Wait for the LoadBalancer to get a public IP (~2 minutes)
kubectl get svc -n n8n -w
```

Once `EXTERNAL-IP` is assigned, note the URL — this is your n8n endpoint.

> **Important:** The n8n deployment uses an EBS PersistentVolumeClaim and `fsGroup: 1000`. This ensures workflow data survives pod restarts. Do not replace the PVC with `emptyDir`.

### 5.3 Install EBS CSI driver (EKS 1.29 requirement)

EKS 1.29 removed the in-tree EBS provisioner. You must install the CSI driver:

```bash
# Get the node role ARN
NODE_ROLE=$(aws eks describe-nodegroup \
  --cluster-name kubeguardian \
  --nodegroup-name default \
  --query "nodegroup.nodeRole" --output text)

# Attach EBS CSI policy
aws iam attach-role-policy \
  --role-name $(basename $NODE_ROLE) \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy

# Install the addon
aws eks create-addon \
  --cluster-name kubeguardian \
  --addon-name aws-ebs-csi-driver \
  --region us-east-1
```

### 5.4 Initial n8n setup

1. Open `http://<n8n-external-ip>:5678` in your browser
2. Create an account (n8n 2.x uses email-based auth)
3. Complete the setup wizard
4. Go to Settings → API → **Create an API key** — save this for Phase 6

### 5.5 Wire Alertmanager to n8n

[infra/kubernetes/monitoring/alertmanager-config.yaml](infra/kubernetes/monitoring/alertmanager-config.yaml) already points to the in-cluster n8n address:

```yaml
url: 'http://n8n.n8n.svc.cluster.local:5678/webhook/kubeguardian-alert'
```

Apply it:

```bash
kubectl apply -f infra/kubernetes/monitoring/alertmanager-config.yaml
```

### 5.6 Build the n8n workflow

Create a new workflow in the n8n UI with 8 nodes in this order:

#### Node 1 — Webhook (trigger)
- Type: **Webhook**
- HTTP Method: `POST`
- Path: `kubeguardian-alert`
- Authentication: None

#### Node 2 — HTTP Request (collect evidence)
- Type: **HTTP Request**
- Method: `POST`
- URL: `http://kubeguardian-agent.ops.svc.cluster.local:8000/evidence`
- Body Content Type: `JSON`
- Body: `{"service": "payment-service", "namespace": "app"}`

#### Node 3 — OpenAI (AI diagnosis)
- Type: **OpenAI**
- Resource: Chat / Message a model
- Model: `gpt-4o`
- Credential: add your OpenAI API key
- System prompt:
```
You are a Kubernetes SRE. Analyze the evidence and respond with ONLY valid JSON:
{"root_cause":"...","confidence":"high|medium|low","steps":["step1"],"recommended_action":"rollout_restart|rollout_undo|scale","service":"payment-service"}
```
- User message: `={{ JSON.stringify($json) }}`

#### Node 4 — Code (parse AI response)
- Type: **Code** (JavaScript)
- Code:
```javascript
const items = $input.all();
const results = [];
for (const item of items) {
  try {
    const j = item.json;
    let raw =
      (j?.output?.[0]?.content?.[0]?.text) ||
      (j?.content?.[0]?.text) ||
      (j?.choices?.[0]?.message?.content) ||
      (j?.text) || JSON.stringify(j);
    const cleaned = raw.replace(/```json\n?/g, '').replace(/```\n?/g, '').trim();
    let diagnosis;
    try { diagnosis = JSON.parse(cleaned); }
    catch (e) { diagnosis = { root_cause: String(raw).slice(0,200), confidence: 'low', steps: [], recommended_action: 'rollout_restart', service: 'payment-service' }; }
    const sd = $getWorkflowStaticData('global');
    sd.lastDiagnosis = diagnosis;
    sd.lastService = diagnosis.service || 'payment-service';
    results.push({ json: diagnosis });
  } catch(e) {
    results.push({ json: { root_cause: e.message, confidence: 'low', steps: [], recommended_action: 'rollout_restart', service: 'payment-service' } });
  }
}
return results;
```

#### Node 5 — Telegram (send alert)
- Type: **Telegram**
- Credential: add your bot token
- Chat ID: your Telegram chat ID
- Parse Mode: Markdown
- Text:
```
🚨 *KubeGuardian Alert*

*Service:* {{ $json.service || 'payment-service' }}
*Root Cause:* {{ $json.root_cause }}
*Confidence:* {{ $json.confidence }}

*Recommended Fix:* `{{ $json.recommended_action }}`

✅ [Click to Approve Fix]({{ $execution.resumeUrl }})
```

#### Node 6 — Wait
- Type: **Wait**
- Resume: `On webhook call`

#### Node 7 — HTTP Request (execute fix)
- Type: **HTTP Request**
- Method: `POST`
- URL: `http://kubeguardian-agent.ops.svc.cluster.local:8000/execute`
- Body:
  - `type` = `={{ $getWorkflowStaticData('global').lastDiagnosis.recommended_action }}`
  - `service` = `={{ $getWorkflowStaticData('global').lastService }}`
  - `namespace` = `app`

#### Node 8 — Telegram (confirm fix)
- Type: **Telegram**
- Text:
```
✅ *Fix Applied*

*Service:* {{ $getWorkflowStaticData('global').lastService }}
*Action:* `{{ $getWorkflowStaticData('global').lastDiagnosis.recommended_action }}`
*Status:* Remediation complete
```

**Save and Publish** the workflow (toggle Inactive → Active in the top-right corner).

---

## Phase 6 — MCP Server (Claude Desktop)

### What this phase builds
- Node.js MCP (Model Context Protocol) server exposing 15 Kubernetes tools to Claude Desktop
- Claude can query your cluster, collect evidence, trigger incidents, log incidents, and view MTTR stats — in plain English

### 6.1 Install MCP server dependencies

```bash
cd mcp-server
npm install
cd ..
```

### 6.2 Configure Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) and add:

```json
{
  "mcpServers": {
    "kubeguardian": {
      "command": "node",
      "args": ["/absolute/path/to/kubeguardian/mcp-server/index.js"],
      "env": {
        "AGENT_URL": "http://localhost:8000",
        "N8N_URL": "http://<your-n8n-elb-url>:5678",
        "N8N_API_KEY": "<your-n8n-api-key>"
      }
    }
  }
}
```

> **Note:** `AGENT_URL` uses `localhost:8000` because the agent lives inside the cluster. Keep a port-forward running whenever you use MCP tools that call the agent:
> ```bash
> kubectl port-forward svc/kubeguardian-agent 8000:8000 -n ops
> ```

### 6.3 Restart Claude Desktop

Quit and reopen Claude Desktop. A hammer icon in the chat input bar confirms the MCP server connected successfully.

### Available MCP tools

| Tool | Description |
|------|-------------|
| `get_pods` | List all pods in a namespace with status |
| `get_pod_logs` | Fetch recent logs from a specific pod |
| `get_events` | Get recent Kubernetes events |
| `describe_deployment` | Full deployment state and conditions |
| `collect_evidence` | Full incident evidence bundle for a service |
| `rollout_restart` | Rolling restart — zero downtime |
| `rollout_undo` | Rollback to previous image |
| `scale_deployment` | Scale replicas up or down |
| `cluster_health` | Overall cluster health summary |
| `trigger_incident` | Simulate crashloop / readiness / errorrate |
| `restore_service` | Restore a service after a simulated incident |
| `trigger_n8n_alert` | Manually fire the n8n alert pipeline |
| `list_n8n_executions` | List recent n8n workflow runs |
| `log_incident` | Log a resolved incident to PostgreSQL with MTTR |
| `get_incident_stats` | Query MTTR statistics per service from the database |

---

## Phase 7 — Argo CD GitOps

### What this phase builds
- Argo CD installed on EKS — watches your GitHub repo
- Any `git push` to `infra/kubernetes/` automatically syncs to the cluster
- Auto-heal: manual `kubectl` changes are reverted to the committed state

### 7.1 Install Argo CD

```bash
kubectl create namespace argocd
kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for all pods to be ready
kubectl wait --for=condition=available --timeout=180s \
  deployment/argocd-server -n argocd
```

### 7.2 Expose the Argo CD UI

```bash
kubectl patch svc argocd-server -n argocd \
  -p '{"spec": {"type": "LoadBalancer"}}'

# Wait for external IP (~2 minutes)
kubectl get svc argocd-server -n argocd -w
```

### 7.3 Get the initial admin password

```bash
kubectl get secret argocd-initial-admin-secret -n argocd \
  -o jsonpath="{.data.password}" | base64 -d && echo
```

> Save this password. You can change it in the Argo CD UI under User Info → Update Password.

### 7.4 Log in to Argo CD

Open `http://<argocd-external-ip>` in your browser.

- Username: `admin`
- Password: the value from step 7.3

> Chrome will show an SSL warning (self-signed cert). Click **Advanced → Proceed** — expected for a self-hosted setup.

### 7.5 Create the Application

```bash
kubectl apply -f infra/kubernetes/argocd/application.yaml
```

This creates an Argo CD Application pointing at your GitHub repo:

```yaml
source:
  repoURL: https://github.com/Eweka01/kubeguardian
  targetRevision: main
  path: infra/kubernetes
```

### 7.6 Verify sync

```bash
kubectl get application kubeguardian -n argocd
```

Expected: `SYNC STATUS: Synced` and `HEALTH STATUS: Healthy`

### How GitOps works from here

```
1. Edit any manifest in infra/kubernetes/
2. git add . && git commit -m "your change" && git push
3. Argo CD detects the change within ~3 minutes
4. Argo CD runs kubectl apply to reconcile the cluster
5. If someone manually edits the cluster, Argo CD reverts it automatically
```

---

## Phase 8 — Incident Database + MTTR Tracking (V2)

### What this phase builds
- PostgreSQL 15 deployed in the `ops` namespace with an EBS-backed PersistentVolumeClaim
- `incidents` table with `mttr_seconds` automatically calculated as a generated column
- FastAPI agent endpoints: `POST /incidents` and `GET /incidents/stats`
- Two new MCP tools: `log_incident` and `get_incident_stats`
- Every resolved incident is recorded — service, type, root cause, action taken, outcome, and MTTR

### 8.1 Deploy PostgreSQL

```bash
kubectl apply -f infra/kubernetes/postgres/deployment.yaml

# Watch the pod come up (takes ~30 seconds)
kubectl get pods -n ops -w
```

### 8.2 Create the incidents table

```bash
kubectl exec -n ops deployment/postgres -- psql -U kubeguardian -d kubeguardian -c "
CREATE TABLE IF NOT EXISTS incidents (
  id               SERIAL PRIMARY KEY,
  service          TEXT NOT NULL,
  namespace        TEXT NOT NULL DEFAULT 'app',
  incident_type    TEXT NOT NULL,
  root_cause       TEXT,
  confidence       TEXT,
  recommended_action TEXT,
  action_taken     TEXT NOT NULL,
  outcome          TEXT NOT NULL DEFAULT 'success',
  detected_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at      TIMESTAMPTZ,
  mttr_seconds     INTEGER GENERATED ALWAYS AS (
    EXTRACT(EPOCH FROM (resolved_at - detected_at))::INTEGER
  ) STORED
);
"
```

### 8.3 Verify the agent can reach PostgreSQL

```bash
# Port-forward to the agent
kubectl port-forward svc/kubeguardian-agent 8000:8000 -n ops

# Log a test incident
curl -X POST http://localhost:8000/incidents \
  -H "Content-Type: application/json" \
  -d '{
    "service": "payment-service",
    "incident_type": "crashloop",
    "root_cause": "OOMKilled — memory limit too low",
    "confidence": "high",
    "recommended_action": "rollout_undo",
    "action_taken": "rollout_undo",
    "outcome": "success"
  }'

# Query stats
curl http://localhost:8000/incidents/stats
```

### 8.4 Use the MCP tools from Claude Desktop

After restarting Claude Desktop with the updated config:

- **Log an incident:** *"Log a crashloop incident for payment-service — root cause was OOMKilled, action taken was rollout_undo, outcome success"*
- **Query MTTR:** *"Show me incident stats for payment-service"*
- **All services:** *"What are the MTTR stats across all services?"*

---

## Claude Desktop — Example Queries

With the port-forward running (`kubectl port-forward svc/kubeguardian-agent 8000:8000 -n ops`) and Claude Desktop restarted, you can use plain English to control and inspect your cluster.

### Cluster inspection

```
"Check cluster health"
"Show me all pods in the app namespace"
"Get the logs for the payment-service pod"
"Describe the payment-service deployment"
"Show me recent events in the app namespace"
```

### Incident simulation and response

```
"Trigger a crashloop on payment-service"
"Simulate a readiness failure on user-service"
"Collect evidence for payment-service — what's wrong?"
"Restart payment-service with a rolling restart"
"Roll back payment-service to the previous image"
"Restore payment-service to healthy"
```

### Incident history and MTTR

```
"Show me incident stats for payment-service"
"What is the average MTTR across all services?"
"Log a resolved incident — service: payment-service, type: crashloop, root cause: OOMKilled, action taken: rollout_undo, outcome: success"
"How many crashloop incidents has payment-service had?"
```

### n8n pipeline

```
"Trigger an n8n alert for payment-service"
"List the last 5 n8n workflow executions"
```

### Scale and capacity

```
"Scale payment-service to 3 replicas"
"Scale api-gateway to 1 replica"
```

---

## End-to-End Demo

Once all phases are complete, run a full incident simulation:

```bash
# 1. Ensure the agent port-forward is running
kubectl port-forward svc/kubeguardian-agent 8000:8000 -n ops &

# 2. Trigger a CrashLoopBackOff on payment-service
./scripts/simulate.sh crashloop payment-service

# 3. Watch pods crash
kubectl get pods -n app -w
```

Within ~1 minute:
- Prometheus fires the `CrashLoopBackOff` alert
- Alertmanager POSTs to n8n
- n8n calls `/evidence` → collects pod logs, events, restart counts
- GPT-4o returns a JSON diagnosis
- **Telegram receives a message** with root cause + recommended fix + approval link

Click the approval link in Telegram:
- n8n resumes execution
- Calls `/execute` with the recommended action
- **Telegram confirms**: "Fix applied — payment-service restored"

Then from Claude Desktop:
```
"Log this incident — payment-service, crashloop, root cause: bad command override, action: rollout_undo, outcome: success"
"Show me incident stats for payment-service"
```

---

## Project Structure

```
kubeguardian/
├── agent/
│   ├── api.py                      # FastAPI — /health /evidence /execute /incidents /incidents/stats
│   ├── Dockerfile                  # python:3.11-slim + kubectl binary
│   ├── requirements.txt
│   └── collector/
│       └── gather.py               # Kubernetes SDK — pods, events, deployments
├── docs/
│   └── incident-types.md           # V1 incident types and safe remediation actions
├── infra/
│   ├── helm/
│   │   ├── install.sh              # One-command observability stack install
│   │   ├── prometheus-values.yaml  # kube-prometheus-stack config
│   │   ├── loki-values.yaml        # Loki log storage config
│   │   └── grafana-values.yaml     # Grafana dashboard config
│   ├── kubernetes/
│   │   ├── agent/
│   │   │   └── deployment.yaml     # ServiceAccount + ClusterRole + Deployment + Service
│   │   ├── argocd/
│   │   │   └── application.yaml    # Argo CD Application — GitOps sync from GitHub
│   │   ├── monitoring/
│   │   │   ├── alert-rules.yaml    # 3 PrometheusRule alerts
│   │   │   └── alertmanager-config.yaml  # Route all alerts → n8n webhook
│   │   ├── n8n/
│   │   │   └── deployment.yaml     # n8n + EBS PVC + Classic ELB LoadBalancer
│   │   ├── namespaces/
│   │   │   └── namespaces.yaml     # app, monitoring, ops namespaces
│   │   ├── postgres/
│   │   │   └── deployment.yaml     # PostgreSQL 15 + EBS PVC + Secret
│   │   └── services/
│   │       ├── api-gateway.yaml
│   │       ├── payment-service.yaml
│   │       └── user-service.yaml
│   └── terraform/
│       ├── main.tf                 # VPC + EKS cluster modules
│       ├── variables.tf            # Region, cluster name, node type
│       ├── outputs.tf              # Cluster name, endpoint, region
│       └── versions.tf             # Provider version pins
├── mcp-server/
│   ├── index.js                    # MCP server — 15 cluster + n8n + incident tools
│   └── package.json
└── scripts/
    └── simulate.sh                 # Incident simulator and restore utility
```

---

## Quick Reference

```bash
# ── Cluster ────────────────────────────────────────────────────────────────
kubectl get nodes
kubectl get pods -n app
kubectl get pods -n monitoring
kubectl get pods -n ops
kubectl get pods -n n8n
kubectl get pods -n argocd

# ── Simulate incidents ─────────────────────────────────────────────────────
./scripts/simulate.sh crashloop payment-service
./scripts/simulate.sh readiness user-service
./scripts/simulate.sh errorrate api-gateway
./scripts/simulate.sh restore <service-name>
./scripts/simulate.sh status

# ── Port-forward UIs ───────────────────────────────────────────────────────
kubectl port-forward svc/grafana 3000:80 -n monitoring
kubectl port-forward svc/prometheus-kube-prometheus-prometheus 9090:9090 -n monitoring
kubectl port-forward svc/prometheus-kube-prometheus-alertmanager 9093:9093 -n monitoring
kubectl port-forward svc/kubeguardian-agent 8000:8000 -n ops     # required for MCP tools

# ── Agent API (while port-forwarded) ───────────────────────────────────────
curl http://localhost:8000/health
curl -X POST http://localhost:8000/evidence \
  -H "Content-Type: application/json" \
  -d '{"service": "payment-service", "namespace": "app"}'
curl http://localhost:8000/incidents/stats

# ── Incident database ──────────────────────────────────────────────────────
kubectl exec -n ops deployment/postgres -- \
  psql -U kubeguardian -d kubeguardian -c "SELECT * FROM incidents ORDER BY detected_at DESC LIMIT 10;"

# ── Argo CD ────────────────────────────────────────────────────────────────
kubectl get application kubeguardian -n argocd
# Force a manual sync
kubectl patch application kubeguardian -n argocd \
  --type merge -p '{"operation":{"sync":{}}}'

# ── Rebuild and redeploy agent ─────────────────────────────────────────────
cd agent
docker buildx build --platform linux/amd64 \
  -t <account-id>.dkr.ecr.us-east-1.amazonaws.com/kubeguardian-agent:latest \
  --push .
kubectl rollout restart deployment/kubeguardian-agent -n ops
cd ..

# ── Tear down everything ───────────────────────────────────────────────────
cd infra/terraform
terraform destroy
```

---

## Build Status

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | EKS cluster + VPC + microservices | Complete |
| Phase 2 | Prometheus + Grafana + Loki + Alertmanager | Complete |
| Phase 3 | Alert rules + incident simulator | Complete |
| Phase 4 | FastAPI agent — evidence collector + executor | Complete |
| Phase 5 | n8n automation + Telegram ChatOps | Complete |
| Phase 6 | MCP server — Claude Desktop integration (15 tools) | Complete |
| Phase 7 | Argo CD GitOps — automated sync from GitHub | Complete |
| Phase 8 | PostgreSQL incident store + MTTR tracking (V2) | Complete |
