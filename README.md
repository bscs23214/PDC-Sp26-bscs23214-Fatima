# Alishba Fatima | bscs23214

## PDC-Sp24-bscs23214-Fatima

### StudySync — Resilient Distributed Systems (Assignment 2)

---

## Overview

This is the Part 3 implementation for PDC Assignment 2.
It fixes the **Lost Update** bug using the **Optimistic Locking** pattern
in a FastAPI document-editing backend.

**Problem:** Two users edit the same document at the same time. The second
user's save silently overwrites the first user's changes with no error raised.

**Fix:** A `version` column is added to every document. Every save must include
the version the client last saw. The database update uses:

```sql
UPDATE documents
   SET body = ?, version = version + 1
 WHERE id = ? AND version = ?   -- version guard
```

If the version no longer matches (someone else saved first), zero rows are
updated and the server returns **HTTP 409 Conflict**. The client must re-fetch,
merge changes, and retry. No data is ever silently lost.

---

## Project Structure

```
.
├── main.py            # FastAPI app — all routes + X-Student-ID middleware
├── optimistic_lock.py # Optimistic Locking pattern implementation
├── test.py            # Test script — shows the bug (before) and the fix (after)
└── README.md
```

---

## Setup & Installation

**Requirements:** Python 3.10+

```bash
# Clone the repo
git clone https://github.com/bscs23214/PDC-Sp26-bscs23214-Fatima.git
cd PDC-Sp24-bscs23214-Fatima

# Create virtual environment
py -3.12 -m venv venv

# Activate it
# Windows PowerShell:
.\venv\Scripts\Activate.ps1
# Mac/Linux:
source venv/bin/activate

# Install dependencies
pip install fastapi uvicorn httpx pydantic starlette
```

---

## Running the Server

```bash
uvicorn main:app --reload --port 8000
```

Open [http://localhost:8000/docs](http://localhost:8000/docs) for the Swagger UI.

Every API response includes the header:
```
X-Student-ID: bscs23214
```

---

## Running the Tests

No server needed. The test script uses FastAPI's built-in test client.

```bash
python test.py
```

**What each scenario shows:**

| Scenario | Description |
|---|---|
| A — No fix | Blind overwrite: Alice's data silently destroyed. No error raised. |
| B — With fix | Alice saves → Bob gets 409 Conflict → Alice's data is safe. |
| B2 — Direct class | Tests OptimisticLock class directly without the API layer. |
| C — Retry | Bob re-fetches, merges, and saves successfully on second attempt. |
| D — Concurrent | Two threads fire at once. Exactly one wins; the other gets 409. |
| Header test | Confirms X-Student-ID: bscs23214 is present on all responses. |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Health check |
| GET | `/health` | Health + lock status |
| GET | `/documents` | List all documents |
| POST | `/documents` | Create a document |
| GET | `/documents/{id}` | Get a document (includes version) |
| PUT | `/documents/{id}` | Update with optimistic locking |
| DELETE | `/documents/{id}` | Delete a document |
| GET | `/lock/status` | Optimistic lock pattern info |

### PUT /documents/{id} — request body

```json
{
  "body": "Updated content",
  "version": 1
}
```

- **200 OK** — saved successfully. New version number returned.
- **409 Conflict** — version is stale. Re-fetch and retry.
- **404 Not Found** — document does not exist.
