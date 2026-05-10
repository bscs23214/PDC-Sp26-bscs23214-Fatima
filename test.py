"""
test.py — StudySync Optimistic Locking Test Suite
Student ID: bscs23214

Run:  python test.py
      (no server needed — uses FastAPI TestClient directly)

Shows:
  Scenario A — WITHOUT the fix: silent lost update (data is destroyed)
  Scenario B — WITH the fix:    409 Conflict returned, data is safe
  Scenario C — Retry flow:      client re-fetches and saves successfully
  Scenario D — Concurrent threads: exactly one writer wins
  Header test — X-Student-ID: bscs23214 on every response
"""

import sys
import os
import threading
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Point DB to a temp file before importing the app ─────────────────────────
import main as app_module
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
app_module.DB_PATH = Path(_tmp.name)
app_module._local  = threading.local()
app_module.init_db()

# ── Also test the OptimisticLock class directly (like friend tests CB directly)
from optimistic_lock import OptimisticLock, VersionConflictError

from fastapi.testclient import TestClient
client = TestClient(app_module.app)


# ── Helpers ───────────────────────────────────────────────────────────────────
def sep(title=""):
    print("\n" + "=" * 60)
    if title:
        print(f"  {title}")
        print("=" * 60)


def create_doc(title="Test Doc", body="Initial body"):
    r = client.post("/documents", json={"title": title, "body": body})
    assert r.status_code == 201, r.text
    return r.json()


# ══════════════════════════════════════════════════════════════════════════════
# Scenario A — WITHOUT the fix: silent lost update
# ══════════════════════════════════════════════════════════════════════════════
def scenario_a_no_fix():
    sep("SCENARIO A — WITHOUT Fix (Naive Blind Overwrite)")
    print("  Both users read version 1 and save. No error raised.")
    print("  Alice's work is silently destroyed by Bob's save.\n")

    doc    = create_doc(body="Original content")
    doc_id = doc["id"]
    conn   = app_module.get_conn()

    alice_body = doc["body"] + " [Alice edit]"
    bob_body   = doc["body"] + " [Bob edit]"

    # Naive UPDATE — no version guard (this is the bug)
    conn.execute("UPDATE documents SET body = ? WHERE id = ?", (alice_body, doc_id))
    conn.commit()
    conn.execute("UPDATE documents SET body = ? WHERE id = ?", (bob_body, doc_id))
    conn.commit()

    final = client.get(f"/documents/{doc_id}").json()["body"]

    print(f"  Alice wrote : '{alice_body}'")
    print(f"  Bob   wrote : '{bob_body}'")
    print(f"  Final state : '{final}'")

    assert "Alice" not in final, "Should have been overwritten"
    print("\n  RESULT: Alice's data SILENTLY LOST — no error was raised.")
    print("          This is the Lost Update bug.\n")


# ══════════════════════════════════════════════════════════════════════════════
# Scenario B — WITH the fix: 409 Conflict returned
# ══════════════════════════════════════════════════════════════════════════════
def scenario_b_with_fix():
    sep("SCENARIO B — WITH Fix (Optimistic Locking via API)")
    print("  Alice saves first. Bob sends stale version → 409 Conflict.\n")

    doc    = create_doc()
    doc_id = doc["id"]

    r_alice = client.put(f"/documents/{doc_id}",
                         json={"body": "Alice's content", "version": 1})
    assert r_alice.status_code == 200, r_alice.text
    print(f"  Alice → HTTP {r_alice.status_code}  version is now {r_alice.json()['version']}")

    r_bob = client.put(f"/documents/{doc_id}",
                       json={"body": "Bob's content", "version": 1})
    assert r_bob.status_code == 409, r_bob.text
    print(f"  Bob   → HTTP {r_bob.status_code}  (expected 409 Conflict)")

    detail = r_bob.json()["detail"]
    print(f"  Error : {detail['message']}")

    final = client.get(f"/documents/{doc_id}").json()["body"]
    assert "Alice" in final
    print(f"  Data  : '{final}' — Alice's work is SAFE\n")


# ══════════════════════════════════════════════════════════════════════════════
# Scenario B2 — OptimisticLock class used directly (unit test)
# ══════════════════════════════════════════════════════════════════════════════
def scenario_b2_direct_class():
    sep("SCENARIO B2 — OptimisticLock class used directly")
    print("  Testing the OptimisticLock helper class without the API layer.\n")

    conn = app_module.get_conn()
    doc  = create_doc(body="Direct lock test")
    lock = OptimisticLock(conn)

    # First save — should work
    result = lock.save(doc_id=doc["id"], body="First save", client_version=1)
    print(f"  Save #1 → version now {result['version']}  (OK)")
    assert result["version"] == 2

    # Second save with stale version — should raise VersionConflictError
    try:
        lock.save(doc_id=doc["id"], body="Stale save", client_version=1)
        assert False, "Should have raised VersionConflictError"
    except VersionConflictError as e:
        print(f"  Save #2 → VersionConflictError raised  (OK)")
        print(f"  Message : {e}")
        assert e.your_version == 1
        assert e.current_version == 2
    print()


# ══════════════════════════════════════════════════════════════════════════════
# Scenario C — Retry flow
# ══════════════════════════════════════════════════════════════════════════════
def scenario_c_retry_flow():
    sep("SCENARIO C — Retry Flow (Re-fetch → Merge → Save)")
    print("  Bob gets a 409, re-fetches the latest version, merges, and retries.\n")

    doc    = create_doc(body="Shared document v1")
    doc_id = doc["id"]

    client.put(f"/documents/{doc_id}",
               json={"body": "Alice's addition", "version": 1})
    print("  Alice  → saved  (version 2)")

    r_fail = client.put(f"/documents/{doc_id}",
                        json={"body": "Bob original", "version": 1})
    assert r_fail.status_code == 409
    print("  Bob #1 → 409 Conflict (stale v1)")

    latest = client.get(f"/documents/{doc_id}").json()
    print(f"  Bob fetches latest → version {latest['version']}, body: '{latest['body']}'")

    merged = latest["body"] + " + Bob's addition"
    r_ok   = client.put(f"/documents/{doc_id}",
                        json={"body": merged, "version": latest["version"]})
    assert r_ok.status_code == 200
    print(f"  Bob #2 → 200 OK  (version {r_ok.json()['version']})")
    print(f"  Final  : '{r_ok.json()['body']}'\n")


# ══════════════════════════════════════════════════════════════════════════════
# Scenario D — Concurrent threads
# ══════════════════════════════════════════════════════════════════════════════
def scenario_d_concurrent():
    sep("SCENARIO D — Two Concurrent Threads")
    print("  Both threads send version 1 at the same time. Exactly one must win.\n")

    doc    = create_doc()
    doc_id = doc["id"]
    results = {}

    def writer(name, body):
        r = client.put(f"/documents/{doc_id}",
                       json={"body": body, "version": 1})
        results[name] = r.status_code

    t1 = threading.Thread(target=writer, args=("Alice", "Alice concurrent"))
    t2 = threading.Thread(target=writer, args=("Bob",   "Bob concurrent"))
    t1.start(); t2.start()
    t1.join();  t2.join()

    print(f"  Alice → HTTP {results['Alice']}")
    print(f"  Bob   → HTTP {results['Bob']}")

    statuses = set(results.values())
    assert 200 in statuses, "One writer must succeed (200)"
    assert 409 in statuses, "One writer must be rejected (409)"

    final = client.get(f"/documents/{doc_id}").json()
    assert final["version"] == 2, f"Expected version 2, got {final['version']}"
    print(f"  Final version: {final['version']} (correct — only one write committed)\n")


# ══════════════════════════════════════════════════════════════════════════════
# Header test
# ══════════════════════════════════════════════════════════════════════════════
def test_headers():
    sep("HEADER TEST — X-Student-ID: bscs23214 on every response")

    checks = [
        ("GET",  "/",            None),
        ("GET",  "/health",      None),
        ("GET",  "/documents",   None),
        ("GET",  "/lock/status", None),
        ("POST", "/documents",   {"title": "T", "body": "B"}),
    ]

    for method, path, body in checks:
        r   = client.get(path) if method == "GET" else client.post(path, json=body)
        hdr = r.headers.get("x-student-id", "MISSING")
        ok  = "OK" if hdr == "bscs23214" else "FAIL"
        print(f"  {method} {path:20s} → {r.status_code} | X-Student-ID: {hdr} [{ok}]")
        assert hdr == "bscs23214"
    print()


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("\n  StudySync — Optimistic Locking Test Suite")
    print("  Part 3: Synchronisation Fix | Student ID: bscs23214\n")

    scenario_a_no_fix()
    scenario_b_with_fix()
    scenario_b2_direct_class()
    scenario_c_retry_flow()
    scenario_d_concurrent()
    test_headers()

    print("=" * 60)
    print("  All scenarios passed.")
    print("=" * 60 + "\n")
