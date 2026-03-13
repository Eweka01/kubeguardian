from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from collector.gather import gather_pod_evidence
import subprocess
import uvicorn
import psycopg2
import psycopg2.extras
import os

PG_HOST = os.getenv("PG_HOST", "postgres.ops.svc.cluster.local")
PG_DB   = os.getenv("PG_DB",   "kubeguardian")
PG_USER = os.getenv("PG_USER", "kubeguardian")
PG_PASS = os.getenv("PG_PASS", "kubeguardian123")

def get_pg():
    return psycopg2.connect(host=PG_HOST, dbname=PG_DB, user=PG_USER, password=PG_PASS)

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

class IncidentLog(BaseModel):
    service: str
    incident_type: str
    root_cause: str = ""
    confidence: str = "low"
    recommended_action: str = ""
    action_taken: str = ""
    outcome: str = "success"
    namespace: str = "app"

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

@app.post("/incidents")
def log_incident(req: IncidentLog):
    try:
        conn = get_pg()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            INSERT INTO incidents
              (service, namespace, incident_type, root_cause, confidence,
               recommended_action, action_taken, outcome, resolved_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            RETURNING id, detected_at, mttr_seconds
        """, (req.service, req.namespace, req.incident_type, req.root_cause,
              req.confidence, req.recommended_action, req.action_taken, req.outcome))
        row = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
        return {"logged": True, "incident_id": row["id"], "detected_at": str(row["detected_at"])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/incidents/stats")
def incident_stats(service: str = None):
    try:
        conn = get_pg()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if service:
            cur.execute("""
                SELECT service, incident_type,
                       COUNT(*) as total,
                       COUNT(resolved_at) as resolved,
                       ROUND(AVG(mttr_seconds)/60.0, 1) as avg_mttr_min,
                       MIN(mttr_seconds/60) as min_mttr_min,
                       MAX(mttr_seconds/60) as max_mttr_min
                FROM incidents WHERE service = %s
                GROUP BY service, incident_type ORDER BY total DESC
            """, (service,))
        else:
            cur.execute("""
                SELECT service, incident_type,
                       COUNT(*) as total,
                       COUNT(resolved_at) as resolved,
                       ROUND(AVG(mttr_seconds)/60.0, 1) as avg_mttr_min,
                       MIN(mttr_seconds/60) as min_mttr_min,
                       MAX(mttr_seconds/60) as max_mttr_min
                FROM incidents
                GROUP BY service, incident_type ORDER BY total DESC
            """)
        rows = cur.fetchall()
        cur.close(); conn.close()
        return {"stats": [dict(r) for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
