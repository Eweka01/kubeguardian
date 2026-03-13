#!/usr/bin/env node
/**
 * KubeGuardian MCP Server
 * Exposes cluster tools so Claude Desktop can query and act on your EKS cluster.
 */

const { Server } = require("@modelcontextprotocol/sdk/server/index.js");
const { StdioServerTransport } = require("@modelcontextprotocol/sdk/server/stdio.js");
const {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} = require("@modelcontextprotocol/sdk/types.js");
const { execSync } = require("child_process");
const axios = require("axios");

const AGENT_URL = process.env.AGENT_URL || "http://localhost:8000";
const N8N_URL = process.env.N8N_URL || "http://a11cf5cd57696406db7e847bbc3f9fc8-509739064.us-east-1.elb.amazonaws.com:5678";
const N8N_API_KEY = process.env.N8N_API_KEY || "";

// ── Helpers ──────────────────────────────────────────────────────────────────

function kubectl(args) {
  try {
    return execSync(`kubectl ${args}`, { encoding: "utf8" }).trim();
  } catch (err) {
    return err.stderr || err.message;
  }
}

// ── Tool definitions ─────────────────────────────────────────────────────────

const TOOLS = [
  {
    name: "get_pods",
    description: "List all pods in a namespace with their status",
    inputSchema: {
      type: "object",
      properties: {
        namespace: { type: "string", description: "Kubernetes namespace (default: app)" }
      }
    }
  },
  {
    name: "get_pod_logs",
    description: "Get recent logs from a pod",
    inputSchema: {
      type: "object",
      required: ["pod_name"],
      properties: {
        pod_name: { type: "string", description: "Full pod name" },
        namespace: { type: "string", description: "Namespace (default: app)" },
        lines: { type: "number", description: "Number of log lines (default: 50)" }
      }
    }
  },
  {
    name: "get_events",
    description: "Get recent Kubernetes events for a namespace",
    inputSchema: {
      type: "object",
      properties: {
        namespace: { type: "string", description: "Namespace (default: app)" }
      }
    }
  },
  {
    name: "describe_deployment",
    description: "Describe a deployment to see its full state, replicas, and conditions",
    inputSchema: {
      type: "object",
      required: ["service"],
      properties: {
        service: { type: "string", description: "Deployment/service name" },
        namespace: { type: "string", description: "Namespace (default: app)" }
      }
    }
  },
  {
    name: "collect_evidence",
    description: "Collect full incident evidence for a service — pods, events, restart counts, deployment state",
    inputSchema: {
      type: "object",
      required: ["service"],
      properties: {
        service: { type: "string", description: "Service name (e.g. payment-service)" },
        namespace: { type: "string", description: "Namespace (default: app)" }
      }
    }
  },
  {
    name: "rollout_restart",
    description: "Safely restart a deployment (rolling restart, zero downtime)",
    inputSchema: {
      type: "object",
      required: ["service"],
      properties: {
        service: { type: "string", description: "Service name" },
        namespace: { type: "string", description: "Namespace (default: app)" }
      }
    }
  },
  {
    name: "rollout_undo",
    description: "Rollback a deployment to the previous image",
    inputSchema: {
      type: "object",
      required: ["service"],
      properties: {
        service: { type: "string", description: "Service name" },
        namespace: { type: "string", description: "Namespace (default: app)" }
      }
    }
  },
  {
    name: "scale_deployment",
    description: "Scale a deployment to a specific number of replicas",
    inputSchema: {
      type: "object",
      required: ["service", "replicas"],
      properties: {
        service: { type: "string", description: "Service name" },
        replicas: { type: "number", description: "Number of replicas" },
        namespace: { type: "string", description: "Namespace (default: app)" }
      }
    }
  },
  {
    name: "cluster_health",
    description: "Get overall cluster health — nodes, pods per namespace, any crashloops",
    inputSchema: {
      type: "object",
      properties: {}
    }
  },
  {
    name: "trigger_incident",
    description: "Simulate a real incident on a service to test the full KubeGuardian pipeline",
    inputSchema: {
      type: "object",
      required: ["incident_type", "service"],
      properties: {
        incident_type: { type: "string", description: "crashloop | readiness | errorrate" },
        service: { type: "string", description: "api-gateway | payment-service | user-service" }
      }
    }
  },
  {
    name: "restore_service",
    description: "Restore a service to healthy state after a simulated incident",
    inputSchema: {
      type: "object",
      required: ["service"],
      properties: {
        service: { type: "string", description: "Service name to restore" }
      }
    }
  },
  {
    name: "trigger_n8n_alert",
    description: "Manually trigger the KubeGuardian n8n alert pipeline for a service",
    inputSchema: {
      type: "object",
      required: ["service"],
      properties: {
        service: { type: "string", description: "Service name (e.g. payment-service)" },
        alertname: { type: "string", description: "Alert name (default: CrashLoopBackOff)" }
      }
    }
  },
  {
    name: "list_n8n_executions",
    description: "List recent n8n workflow executions and their status",
    inputSchema: {
      type: "object",
      properties: {
        limit: { type: "number", description: "Number of executions to return (default: 5)" }
      }
    }
  }
];

// ── Tool handlers ─────────────────────────────────────────────────────────────

async function handleTool(name, args) {
  const ns = args.namespace || "app";

  switch (name) {

    case "get_pods":
      return kubectl(`get pods -n ${ns} -o wide`);

    case "get_pod_logs": {
      const lines = args.lines || 50;
      return kubectl(`logs ${args.pod_name} -n ${ns} --tail=${lines}`);
    }

    case "get_events":
      return kubectl(`get events -n ${ns} --sort-by='.lastTimestamp'`);

    case "describe_deployment":
      return kubectl(`describe deployment ${args.service} -n ${ns}`);

    case "collect_evidence": {
      const res = await axios.post(`${AGENT_URL}/evidence`, {
        service: args.service,
        namespace: ns
      });
      return JSON.stringify(res.data, null, 2);
    }

    case "rollout_restart": {
      const res = await axios.post(`${AGENT_URL}/execute`, {
        type: "rollout_restart",
        service: args.service,
        namespace: ns
      });
      return JSON.stringify(res.data, null, 2);
    }

    case "rollout_undo": {
      const res = await axios.post(`${AGENT_URL}/execute`, {
        type: "rollout_undo",
        service: args.service,
        namespace: ns
      });
      return JSON.stringify(res.data, null, 2);
    }

    case "scale_deployment": {
      const res = await axios.post(`${AGENT_URL}/execute`, {
        type: "scale",
        service: args.service,
        namespace: ns,
        replicas: args.replicas
      });
      return JSON.stringify(res.data, null, 2);
    }

    case "trigger_incident": {
      const script = `/Users/osamudiameneweka/kubeguardian/scripts/simulate.sh`;
      return kubectl(`--version`) && execSync(`bash ${script} ${args.incident_type} ${args.service}`, { encoding: "utf8" });
    }

    case "restore_service": {
      const script = `/Users/osamudiameneweka/kubeguardian/scripts/simulate.sh`;
      return execSync(`bash ${script} restore ${args.service}`, { encoding: "utf8" });
    }

    case "trigger_n8n_alert": {
      const alertname = args.alertname || "CrashLoopBackOff";
      const res = await axios.post(
        `${N8N_URL}/webhook/kubeguardian-alert`,
        {
          receiver: "n8n-webhook",
          status: "firing",
          alerts: [{ status: "firing", labels: { alertname, namespace: "app", severity: "critical" } }],
          groupLabels: { alertname, service: args.service },
          commonLabels: { namespace: "app", service: args.service }
        }
      );
      return `n8n triggered: ${JSON.stringify(res.data)}`;
    }

    case "list_n8n_executions": {
      const limit = args.limit || 5;
      const headers = N8N_API_KEY ? { "X-N8N-API-KEY": N8N_API_KEY } : {};
      const res = await axios.get(`${N8N_URL}/api/v1/executions?limit=${limit}`, { headers });
      return JSON.stringify(res.data, null, 2);
    }

    case "cluster_health": {
      const nodes   = kubectl("get nodes");
      const appPods = kubectl("get pods -n app");
      const opsPods = kubectl("get pods -n ops");
      const monPods = kubectl("get pods -n monitoring --no-headers | wc -l");
      const crashes = kubectl("get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded --no-headers 2>/dev/null || echo 'none'");
      return [
        "=== NODES ===", nodes,
        "\n=== APP PODS ===", appPods,
        "\n=== OPS PODS ===", opsPods,
        "\n=== MONITORING PODS (count) ===", monPods,
        "\n=== NON-RUNNING PODS (all namespaces) ===", crashes
      ].join("\n");
    }

    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}

// ── Server setup ─────────────────────────────────────────────────────────────

const server = new Server(
  { name: "kubeguardian-mcp", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  try {
    const result = await handleTool(name, args || {});
    return {
      content: [{ type: "text", text: String(result) }]
    };
  } catch (err) {
    return {
      content: [{ type: "text", text: `Error: ${err.message}` }],
      isError: true
    };
  }
});

// ── Start ─────────────────────────────────────────────────────────────────────

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("KubeGuardian MCP server running (stdio)");
}

main().catch(console.error);
