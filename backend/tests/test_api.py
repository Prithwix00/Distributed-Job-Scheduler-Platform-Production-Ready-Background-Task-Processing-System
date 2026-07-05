def _make_queue(auth_client):
    p = auth_client.post("/api/v1/projects", json={"name": "P", "slug": "p"})
    project_id = p.json()["id"]
    q = auth_client.post(f"/api/v1/projects/{project_id}/queues", json={
        "name": "default", "concurrency_limit": 50,
        "retry_policy": {"strategy": "fixed", "max_attempts": 2, "base_delay_seconds": 0},
    })
    return q.json()["id"]


def test_register_login_me(client):
    r = client.post("/api/v1/auth/register", json={
        "organization_name": "Beta", "email": "a@b.example.com", "password": "password123"})
    assert r.status_code == 201
    token = r.json()["access_token"]

    r = client.post("/api/v1/auth/login", json={"email": "a@b.example.com", "password": "password123"})
    assert r.status_code == 200

    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["email"] == "a@b.example.com"
    assert r.json()["role"] == "owner"


def test_auth_required(client):
    assert client.get("/api/v1/projects").status_code == 401


def test_duplicate_email_conflicts(client):
    body = {"organization_name": "Xco", "email": "dup@x.example.com", "password": "password123"}
    assert client.post("/api/v1/auth/register", json=body).status_code == 201
    assert client.post("/api/v1/auth/register", json=body).status_code == 409


def test_create_and_list_jobs(auth_client):
    qid = _make_queue(auth_client)
    r = auth_client.post(f"/api/v1/queues/{qid}/jobs", json={
        "task_name": "echo", "payload": {"hello": "world"}})
    assert r.status_code == 201
    assert r.json()["state"] == "queued"

    r = auth_client.get(f"/api/v1/queues/{qid}/jobs")
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["task_name"] == "echo"


def test_pause_resume_queue(auth_client):
    qid = _make_queue(auth_client)
    assert auth_client.post(f"/api/v1/queues/{qid}/pause").json()["is_paused"] is True
    assert auth_client.post(f"/api/v1/queues/{qid}/resume").json()["is_paused"] is False


def test_scheduled_job_validation(auth_client):
    qid = _make_queue(auth_client)
    # recurring without cron -> 422
    r = auth_client.post(f"/api/v1/queues/{qid}/jobs", json={
        "task_name": "echo", "job_type": "recurring"})
    assert r.status_code == 422


def test_full_worker_pipeline(auth_client):
    """Drive a job end to end through the worker-facing HTTP contract:
    register -> claim -> start -> result. This exercises the same endpoints the
    worker process calls, proving the whole pipeline without a second process."""
    qid = _make_queue(auth_client)
    auth_client.post(f"/api/v1/queues/{qid}/jobs", json={
        "task_name": "echo", "payload": {"n": 42}})

    w = auth_client.post("/api/v1/workers/register", json={
        "hostname": "test-host", "queues": [qid], "concurrency": 4})
    wid = w.json()["id"]

    claimed = auth_client.post(f"/api/v1/workers/{wid}/claim", json={
        "worker_id": wid, "limit": 5, "lease_seconds": 30}).json()
    assert len(claimed) == 1
    job_id = claimed[0]["id"]

    start = auth_client.post(f"/api/v1/workers/{wid}/jobs/{job_id}/start").json()
    exec_id = start["execution_id"]

    done = auth_client.post(f"/api/v1/workers/{wid}/jobs/{job_id}/result", json={
        "execution_id": exec_id, "success": True, "result": {"echoed": {"n": 42}}})
    assert done.json()["state"] == "completed"

    detail = auth_client.get(f"/api/v1/jobs/{job_id}").json()
    assert len(detail["executions"]) == 1
    assert detail["executions"][0]["status"] == "succeeded"
    assert len(detail["logs"]) >= 2


def test_dead_letter_and_replay_via_api(auth_client):
    qid = _make_queue(auth_client)  # max_attempts = 2
    auth_client.post(f"/api/v1/queues/{qid}/jobs", json={"task_name": "fail"})
    w = auth_client.post("/api/v1/workers/register", json={
        "hostname": "h", "queues": [qid], "concurrency": 1}).json()
    wid = w["id"]

    def attempt():
        claimed = auth_client.post(f"/api/v1/workers/{wid}/claim", json={
            "worker_id": wid, "limit": 1, "lease_seconds": 30}).json()
        if not claimed:
            return None
        jid = claimed[0]["id"]
        s = auth_client.post(f"/api/v1/workers/{wid}/jobs/{jid}/start").json()
        return auth_client.post(f"/api/v1/workers/{wid}/jobs/{jid}/result", json={
            "execution_id": s["execution_id"], "success": False, "error": "nope"}).json()

    first = attempt()
    assert first["state"] == "scheduled"  # retry queued

    # promote the retry, then fail again -> dead
    from app.services import scheduling
    from app.database import SessionLocal
    scheduling.promote_due_scheduled(SessionLocal())
    second = attempt()
    assert second["state"] == "dead"

    dlq = auth_client.get(f"/api/v1/queues/{qid}/dead-letters").json()
    assert dlq["total"] == 1
    entry_id = dlq["items"][0]["id"]

    replayed = auth_client.post(f"/api/v1/dead-letters/{entry_id}/replay").json()
    assert replayed["state"] == "queued"


def test_dashboard_overview(auth_client):
    qid = _make_queue(auth_client)
    auth_client.post(f"/api/v1/queues/{qid}/jobs", json={"task_name": "echo"})
    ov = auth_client.get("/api/v1/dashboard/overview").json()
    assert ov["jobs"]["queued"] == 1
    assert "success_rate" in ov
