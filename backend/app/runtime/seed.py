"""Seed a demo workspace with a project, queues and a mix of job types.

Usage (with the API running on :8000):
    python -m app.runtime.seed            # uses http://localhost:8000
    python -m app.runtime.seed --base-url http://api:8000
"""
from __future__ import annotations

import argparse

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    b = f"{args.base_url.rstrip('/')}/api/v1"
    c = httpx.Client(timeout=15)

    # Register (or fall back to login if the demo user already exists).
    reg = c.post(f"{b}/auth/register", json={
        "organization_name": "Demo Corp", "email": "demo@example.com",
        "password": "password123", "full_name": "Demo User",
    })
    if reg.status_code == 201:
        token = reg.json()["access_token"]
    else:
        token = c.post(f"{b}/auth/login", json={
            "email": "demo@example.com", "password": "password123"
        }).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # Helper function to create project or get existing one
    def get_or_create_project(name: str, slug: str) -> dict:
        # Try to create
        resp = c.post(f"{b}/projects", json={"name": name, "slug": slug}, headers=h)
        if resp.status_code == 201:
            return resp.json()
        # If exists, get all projects and find it
        projects = c.get(f"{b}/projects", headers=h).json()
        for p in projects:
            if p["slug"] == slug:
                return p
        raise ValueError(f"Could not create or find project {slug}")

    # Project 1: Payments
    project1 = get_or_create_project("Payments", "payments")
    pid1 = project1["id"]

    # Helper for queues
    def get_or_create_queue(project_id: str, name: str, priority: int, concurrency: int, retry_policy: dict) -> dict:
        resp = c.post(f"{b}/projects/{project_id}/queues", json={
            "name": name, "priority": priority, "concurrency_limit": concurrency,
            "retry_policy": retry_policy,
        }, headers=h)
        if resp.status_code == 201:
            return resp.json()
        # If exists, get all queues and find it
        queues = c.get(f"{b}/projects/{project_id}/queues", headers=h).json()
        for q in queues:
            if q["name"] == name:
                return q
        raise ValueError(f"Could not create or find queue {name}")

    emails = get_or_create_queue(pid1, "emails", 5, 8, {
        "strategy": "exponential", "max_attempts": 4,
        "base_delay_seconds": 2, "backoff_factor": 2, "jitter": 0.2
    })
    
    transactions = get_or_create_queue(pid1, "transactions", 10, 16, {
        "strategy": "exponential", "max_attempts": 5,
        "base_delay_seconds": 1, "backoff_factor": 1.5, "jitter": 0.1
    })
    
    reports = get_or_create_queue(pid1, "reports", 1, 3, {
        "strategy": "linear", "max_attempts": 3, "base_delay_seconds": 5
    })

    # Project 2: Analytics
    project2 = get_or_create_project("Analytics", "analytics")
    pid2 = project2["id"]

    analytics_queue = get_or_create_queue(pid2, "events", 2, 32, {
        "strategy": "linear", "max_attempts": 2, "base_delay_seconds": 3
    })
    
    export_queue = get_or_create_queue(pid2, "exports", 3, 2, {
        "strategy": "exponential", "max_attempts": 4,
        "base_delay_seconds": 5, "backoff_factor": 2, "jitter": 0.3
    })

    # Project 3: Notifications
    project3 = get_or_create_project("Notifications", "notifications")
    pid3 = project3["id"]

    notifications = get_or_create_queue(pid3, "sms", 8, 20, {
        "strategy": "exponential", "max_attempts": 3,
        "base_delay_seconds": 2, "backoff_factor": 2, "jitter": 0.2
    })
    
    push_queue = get_or_create_queue(pid3, "push-notifications", 7, 50, {
        "strategy": "linear", "max_attempts": 2, "base_delay_seconds": 1
    })

    # ===== PAYMENTS PROJECT JOBS =====
    
    # Emails: 15 normal + 1 flaky + 1 failed
    for i in range(15):
        c.post(f"{b}/queues/{emails['id']}/jobs", json={
            "task_name": "send_email",
            "payload": {"to": f"customer{i}@acme.com", "subject": f"Invoice #{10001+i}", "body": "Your payment is due."},
        }, headers=h)
    c.post(f"{b}/queues/{emails['id']}/jobs", json={
        "task_name": "flaky_email", "payload": {"succeed_on": 2, "to": "retry@example.com"}}, headers=h)
    c.post(f"{b}/queues/{emails['id']}/jobs", json={
        "task_name": "send_email", "payload": {"to": "invalid@test.local", "subject": "Bad address"}}, headers=h)

    # Transactions: 25 normal transactions
    for i in range(25):
        amount = (i + 1) * 100
        c.post(f"{b}/queues/{transactions['id']}/jobs", json={
            "task_name": "process_transaction",
            "payload": {"tx_id": f"TXN-{i:05d}", "amount": amount, "currency": "USD", "from": f"acc-{i%5}", "to": f"acc-{(i+1)%5}"},
        }, headers=h)

    # Reports: 5 jobs with delays
    for i in range(5):
        c.post(f"{b}/queues/{reports['id']}/jobs", json={
            "task_name": "generate_report",
            "payload": {"report_type": f"daily_{i+1}", "format": "pdf"},
            "job_type": "delayed", "delay_seconds": 5 * i,
        }, headers=h)

    # Scheduled: Hourly and daily reports
    c.post(f"{b}/queues/{reports['id']}/schedules", json={
        "name": "hourly-payment-report", "task_name": "generate_payment_report",
        "payload": {"period": "hourly"}, "cron_expression": "0 * * * *"}, headers=h)
    c.post(f"{b}/queues/{reports['id']}/schedules", json={
        "name": "daily-reconciliation", "task_name": "reconcile_payments",
        "payload": {"period": "daily"}, "cron_expression": "0 2 * * *"}, headers=h)

    # ===== ANALYTICS PROJECT JOBS =====

    # Events: 30 tracking events
    event_types = ["page_view", "button_click", "form_submit", "item_purchase", "user_signup"]
    for i in range(30):
        c.post(f"{b}/queues/{analytics_queue['id']}/jobs", json={
            "task_name": "track_event",
            "payload": {
                "event": event_types[i % len(event_types)],
                "user_id": f"user-{i%20}",
                "timestamp": f"2024-01-{(i%28)+1:02d}",
                "properties": {"session": f"sess-{i//10}", "device": "web" if i % 2 == 0 else "mobile"}
            },
        }, headers=h)

    # Exports: 3 CSV export jobs with delays
    for i in range(3):
        c.post(f"{b}/queues/{export_queue['id']}/jobs", json={
            "task_name": "export_data",
            "payload": {"format": "csv", "table": f"table_{i}", "size_mb": (i+1)*50},
            "job_type": "delayed", "delay_seconds": 10,
        }, headers=h)

    # ===== NOTIFICATIONS PROJECT JOBS =====

    # SMS: 12 SMS messages
    for i in range(12):
        c.post(f"{b}/queues/{notifications['id']}/jobs", json={
            "task_name": "send_sms",
            "payload": {"phone": f"+1555000{i:04d}", "message": f"Your code: {1000+i}"},
        }, headers=h)

    # Push notifications: 20 push messages
    for i in range(20):
        c.post(f"{b}/queues/{push_queue['id']}/jobs", json={
            "task_name": "send_push",
            "payload": {
                "device_token": f"token-{i:04d}",
                "title": f"Notification {i+1}",
                "body": f"You have an update waiting.",
                "priority": "high" if i % 3 == 0 else "normal"
            },
        }, headers=h)

    # Scheduled push notifications
    c.post(f"{b}/queues/{push_queue['id']}/schedules", json={
        "name": "daily-digest", "task_name": "send_daily_digest",
        "payload": {"digest_type": "summary"}, "cron_expression": "0 9 * * *"}, headers=h)

    print("\n✅ Seeded demo workspace with 3 projects!")
    print("  Login: demo@example.com / password123")
    print("\n📊 Projects created:")
    print(f"  1. Payments (3 queues, 41 jobs)")
    print(f"  2. Analytics (2 queues, 33 jobs)")
    print(f"  3. Notifications (2 queues, 32 jobs)")
    print("\n📈 Total: 7 queues, 106 jobs, 3 scheduled tasks")


if __name__ == "__main__":
    main()
