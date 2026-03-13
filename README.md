# KubeGuardian AI

> AI-assisted Kubernetes incident triage and automated remediation platform. Detects real incidents on EKS, collects evidence, runs AI diagnosis, and executes safe fixes — all triggered from Telegram.

---

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
12. [End-to-End Demo](#end-to-end-demo)
13. [Project Structure](#project-structure)
14. [Quick Reference](#quick-reference)

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

The entire stack runs on Kubernetes and is managed via GitOps with Argo CD.

---

## Architecture

```
                        ┌─────────────────────────────────────────┐
                        │             AWS EKS Cluster             │
                        │                                         │
  Prometheus ──scrapes──▶  app namespace                         │
  Alertmanager ─fires──▶    ├── api-gateway      (2 pods)        │
  Loki ──────collects──▶    ├── payment-service  (2 pods)        │
                        │    └── user-service    (2 pods)         │
                        │                                         │
                        │  ops namespace                          │
                        │    └── kubeguardian-agent  (FastAPI)    │
                        │                                         │
                        │  n8n namespace                          │
                        │    └── n8n  (internet-facing ELB)       │
                        │                                         │
                        │  argocd namespace                       │
                        │    └── argocd-server  (GitOps)          │
                        └─────────────────────────────────────────┘
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
                            ← query cluster directly →
```

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Cloud | AWS (EKS, ECR, VPC, Classic ELB) |
| Infrastructure as Code | Terraform (`terraform-aws-modules/eks` v20, `vpc` v5) |
| Container orchestration | Kubernetes 1.29 |
| Metrics | Prometheus + kube-state-metrics + node-exporter |
| Dashboards | Grafana |
| Logs | Loki + Promtail |
| Alerting | Alertmanager |
| Automation | n8n (self-hosted on EKS) |
| Agent API | FastAPI + Python Kubernetes SDK |
| AI diagnosis | GPT-4o (OpenAI) or Claude (Anthropic) |
| ChatOps | Telegram Bot API |
| MCP integration | Model Context Protocol server (Node.js) |
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
- EKS cluster (Kubernetes 1.29) with a managed node group
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

If you see `Error: server has asked for the client to provide credentials`, your IAM user is not yet mapped to the cluster. Run:

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

This is required for LoadBalancer services (n8n, Argo CD) to get public IPs:

```bash
# Get your public subnet IDs
aws ec2 describe-subnets \
  --filters "Name=tag:Name,Values=kubeguardian-vpc-public*" \
  --query "Subnets[*].SubnetId" \
  --output text

# Tag each public subnet (repeat for both subnet IDs)
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
| Nodes | 2 × `t3.medium` (auto-scales 1–3) |
| VPC CIDR | `10.0.0.0/16` |
| Private subnets | `10.0.1.0/24`, `10.0.2.0/24` |
| Public subnets | `10.0.101.0/24`, `10.0.102.0/24` |

---

## Phase 2 — Observability Stack

### What this phase builds
- Prometheus — scrapes metrics from all pods and nodes
- Alertmanager — fires alerts, routes to n8n webhook
- Grafana — dashboards
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

To re-install everything at once, use the helper script:

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
- Python FastAPI service with two endpoints: evidence collection and safe remediation
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

### Allow-listed actions (no arbitrary kubectl)

| Action | Effect |
|--------|--------|
| `rollout_restart` | Rolling restart — zero downtime |
| `rollout_undo` | Rollback to the previous image |
| `scale` | Scale replicas up or down |

---

## Phase 5 — n8n Automation + Telegram ChatOps

### What this phase builds
- n8n workflow automation engine deployed on EKS with a public LoadBalancer
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

### 5.3 Initial n8n setup

1. Open `http://<n8n-external-ip>:5678` in your browser
2. Create an account (n8n 2.x uses email-based auth):
   - Email: `admin@yourdomain.local`
   - Password: choose a strong password
3. Complete the setup wizard

### 5.4 Wire Alertmanager to n8n

Update [infra/kubernetes/monitoring/alertmanager-config.yaml](infra/kubernetes/monitoring/alertmanager-config.yaml) — the webhook URL is already set to the in-cluster n8n address:

```yaml
url: 'http://n8n.n8n.svc.cluster.local:5678/webhook/kubeguardian-alert'
```

Apply the config:

```bash
kubectl apply -f infra/kubernetes/monitoring/alertmanager-config.yaml
```

### 5.5 Build the n8n workflow

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
- Body:
```json
{
  "service": "payment-service",
  "namespace": "app"
}
```

#### Node 3 — OpenAI (AI diagnosis)
- Type: **OpenAI**
- Resource: Chat
- Model: `gpt-4o`
- Credential: add your OpenAI API key
- System prompt:
```
You are a Kubernetes SRE. Analyze the evidence and respond with ONLY valid JSON:
{
  "root_cause": "...",
  "confidence": "high|medium|low",
  "steps": ["step1", "step2"],
  "recommended_action": "rollout_restart|rollout_undo|scale"
}
```
- User message: `={{ JSON.stringify($json) }}`

#### Node 4 — Code (parse AI response)
- Type: **Code** (JavaScript)
- Code:
```javascript
const items = $input.all();
const results = [];

for (const item of items) {
  let raw = "";
  if (item.json.content && item.json.content[0] && item.json.content[0].text) {
    raw = item.json.content[0].text;
  } else if (item.json.message && item.json.message.content) {
    raw = item.json.message.content;
  } else if (typeof item.json.text === "string") {
    raw = item.json.text;
  } else {
    raw = JSON.stringify(item.json);
  }

  const cleaned = raw.replace(/```json\n?/g, "").replace(/```\n?/g, "").trim();
  let diagnosis;
  try {
    diagnosis = JSON.parse(cleaned);
  } catch (e) {
    diagnosis = { root_cause: raw, confidence: "low", steps: [], recommended_action: "rollout_restart" };
  }

  // Persist for use after the Wait node
  const staticData = $getWorkflowStaticData("global");
  staticData.lastDiagnosis = diagnosis;
  staticData.lastService = "payment-service";

  results.push({ json: diagnosis });
}

return results;
```

#### Node 5 — Telegram (send alert)
- Type: **Telegram**
- Credential: add your bot token
- Chat ID: your Telegram chat ID
- Text:
```
🚨 KubeGuardian Alert

Service: payment-service
Root Cause: {{ $json.root_cause }}
Confidence: {{ $json.confidence }}

Steps:
{{ $json.steps.join('\n') }}

Recommended Fix: {{ $json.recommended_action }}

To approve: click the link below
{{ $execution.resumeUrl }}
```

#### Node 6 — Wait
- Type: **Wait**
- Resume: `On webhook call`
- This node pauses the workflow until you click the `resumeUrl` from Telegram

#### Node 7 — HTTP Request (execute fix)
- Type: **HTTP Request**
- Method: `POST`
- URL: `http://kubeguardian-agent.ops.svc.cluster.local:8000/execute`
- Body Content Type: `JSON`
- Body:
```javascript
// In "Using Fields Below" mode:
// type  = {{ $getWorkflowStaticData('global').lastDiagnosis.recommended_action }}
// service = {{ $getWorkflowStaticData('global').lastService }}
// namespace = app
```

#### Node 8 — Telegram (confirm fix)
- Type: **Telegram**
- Credential: same bot
- Chat ID: same chat ID
- Text:
```
✅ Fix Applied

Service: {{ $getWorkflowStaticData('global').lastService }}
Action: {{ $getWorkflowStaticData('global').lastDiagnosis.recommended_action }}
Status: Remediation complete
```

**Activate the workflow** by toggling the switch in the top right corner from Inactive → Active.

---

## Phase 6 — MCP Server (Claude Desktop)

### What this phase builds
- Node.js MCP (Model Context Protocol) server that exposes 14 Kubernetes tools to Claude Desktop
- Claude can query your cluster, collect evidence, trigger incidents, and call n8n directly from chat

### 6.1 Install MCP server dependencies

```bash
cd mcp-server
npm install
cd ..
```

### 6.2 Get your n8n API key

1. Open n8n → top-right menu → **Settings** → **API**
2. Click **Create an API key**
3. Copy the key

### 6.3 Configure Claude Desktop

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

> **Note:** `AGENT_URL` uses `localhost:8000` because the agent is inside the cluster. Run `kubectl port-forward svc/kubeguardian-agent 8000:8000 -n ops` whenever you want to use MCP tools that call the agent.

### 6.4 Restart Claude Desktop

Quit and reopen Claude Desktop. You should see a tools icon (hammer) in the chat bar — this confirms the MCP server connected.

### Available MCP tools

| Tool | Description |
|------|-------------|
| `get_pods` | List all pods in a namespace with status |
| `get_pod_logs` | Fetch recent logs from a specific pod |
| `get_events` | Get recent Kubernetes events |
| `describe_deployment` | Full deployment state and conditions |
| `collect_evidence` | Full incident evidence bundle for a service |
| `rollout_restart` | Rolling restart (zero downtime) |
| `rollout_undo` | Rollback to previous image |
| `scale_deployment` | Scale replicas |
| `cluster_health` | Overall cluster health summary |
| `trigger_incident` | Simulate a crashloop / readiness / errorrate incident |
| `restore_service` | Restore a service after a simulated incident |
| `trigger_n8n_alert` | Manually fire the n8n alert pipeline |
| `list_n8n_executions` | List recent n8n workflow runs |

---

## Phase 7 — Argo CD GitOps

### What this phase builds
- Argo CD installed on EKS — watches your GitHub repo
- Any `git push` to `infra/kubernetes/` automatically syncs to the cluster
- Auto-heal: manual `kubectl` changes are reverted back to the git state

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

> **Save this password.** You can change it in the Argo CD UI under User Info → Update Password.

### 7.4 Log in to Argo CD

Open `http://<argocd-external-ip>` in your browser.

- Username: `admin`
- Password: the value from step 7.3

> Chrome will show an SSL warning (self-signed cert). Click **Advanced → Proceed** — this is expected for a self-hosted setup.

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
5. If someone manually edits the cluster (kubectl patch), Argo CD reverts it
```

---

## End-to-End Demo

Once all phases are complete, run a full incident simulation:

```bash
# 1. Port-forward the agent (required for MCP tools)
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
- Calls `/execute` with `rollout_undo`
- `kubectl rollout undo` restores the previous healthy image
- **Telegram confirms**: "Fix applied — payment-service restored"

---

## Project Structure

```
kubeguardian/
├── agent/
│   ├── api.py                      # FastAPI app — /health, /evidence, /execute
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
│   │   │   └── deployment.yaml     # n8n + Classic ELB LoadBalancer Service
│   │   ├── namespaces/
│   │   │   └── namespaces.yaml     # app, monitoring, ops namespaces
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
│   ├── index.js                    # MCP server — 14 cluster + n8n tools
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
kubectl port-forward svc/kubeguardian-agent 8000:8000 -n ops

# ── Agent API (while port-forwarded) ───────────────────────────────────────
curl http://localhost:8000/health
curl -X POST http://localhost:8000/evidence \
  -H "Content-Type: application/json" \
  -d '{"service": "payment-service", "namespace": "app"}'

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
| Phase 1 | EKS cluster + VPC + microservices | ✅ Complete |
| Phase 2 | Prometheus + Grafana + Loki + Alertmanager | ✅ Complete |
| Phase 3 | Alert rules + incident simulator | ✅ Complete |
| Phase 4 | FastAPI agent — evidence collector + executor | ✅ Complete |
| Phase 5 | n8n automation + Telegram ChatOps | ✅ Complete |
| Phase 6 | MCP server — Claude Desktop integration | ✅ Complete |
| Phase 7 | Argo CD GitOps — automated sync from GitHub | ✅ Complete |
