from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from collector.gather import gather_pod_evidence
import subprocess
import uvicorn

app = FastAPI(title="KubeGuardian Agent API")

# ── Models ──────────────────────────────────────────────
class EvidenceRequest(BaseModel):
    service: str
    namespace: str = "app"

class ExecuteRequest(BaseModel):
    type: str
    service: str
    namespace: str = "app"
    replicas: int = 3

# ── Allow-list ───────────────────────────────────────────
ALLOWED_ACTIONS = {
    "rollout_restart": lambda s, ns, **_: [
        "kubectl", "rollout", "restart",
        f"deployment/{s}", "-n", ns
    ],
    "rollout_undo": lambda s, ns, **_: [
        "kubectl", "rollout", "undo",
        f"deployment/{s}", "-n", ns
    ],
    "scale": lambda s, ns, replicas=3, **_: [
        "kubectl", "scale", f"deployment/{s}",
        f"--replicas={replicas}", "-n", ns
    ]
}

# ── Routes ───────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "service": "kubeguardian-agent"}

@app.post("/evidence")
def get_evidence(req: EvidenceRequest):
    try:
        return gather_pod_evidence(req.namespace, req.service)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/execute")
def execute_action(req: ExecuteRequest):
    if req.type not in ALLOWED_ACTIONS:
        raise HTTPException(
            status_code=403,
            detail=f"'{req.type}' is not an allowed action. "
                   f"Allowed: {list(ALLOWED_ACTIONS.keys())}"
        )

    cmd = ALLOWED_ACTIONS[req.type](
        req.service, req.namespace, replicas=req.replicas
    )

    result = subprocess.run(cmd, capture_output=True, text=True)

    return {
        "success": result.returncode == 0,
        "action": req.type,
        "service": req.service,
        "namespace": req.namespace,
        "output": result.stdout.strip(),
        "error": result.stderr.strip() if result.returncode != 0 else None
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
