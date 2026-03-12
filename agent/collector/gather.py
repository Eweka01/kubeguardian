from kubernetes import client, config
from datetime import datetime, timezone

def gather_pod_evidence(namespace: str, service: str) -> dict:
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()

    v1 = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()

    evidence = {
        "service": service,
        "namespace": namespace,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pods": [],
        "events": [],
        "deployment": {}
    }

    # Pod details
    pods = v1.list_namespaced_pod(namespace, label_selector=f"app={service}")
    for pod in pods.items:
        pod_info = {
            "name": pod.metadata.name,
            "phase": pod.status.phase,
            "conditions": [],
            "containers": []
        }
        if pod.status.conditions:
            for cond in pod.status.conditions:
                pod_info["conditions"].append({
                    "type": cond.type,
                    "status": cond.status,
                    "reason": cond.reason,
                    "message": cond.message
                })
        if pod.status.container_statuses:
            for cs in pod.status.container_statuses:
                state = {}
                if cs.state.running:
                    state = {"running": True}
                elif cs.state.waiting:
                    state = {"waiting": True, "reason": cs.state.waiting.reason, "message": cs.state.waiting.message}
                elif cs.state.terminated:
                    state = {"terminated": True, "exit_code": cs.state.terminated.exit_code, "reason": cs.state.terminated.reason}
                pod_info["containers"].append({
                    "name": cs.name,
                    "ready": cs.ready,
                    "restart_count": cs.restart_count,
                    "state": state
                })
        evidence["pods"].append(pod_info)

    # Recent events
    events = v1.list_namespaced_event(namespace, field_selector=f"involvedObject.name={service}")
    for event in sorted(events.items, key=lambda e: e.last_timestamp or datetime.min.replace(tzinfo=timezone.utc))[-10:]:
        evidence["events"].append({
            "reason": event.reason,
            "message": event.message,
            "count": event.count,
            "type": event.type
        })

    # Deployment info
    try:
        dep = apps_v1.read_namespaced_deployment(service, namespace)
        evidence["deployment"] = {
            "desired_replicas": dep.spec.replicas,
            "ready_replicas": dep.status.ready_replicas,
            "available_replicas": dep.status.available_replicas,
            "image": dep.spec.template.spec.containers[0].image
        }
    except Exception:
        pass

    return evidence
