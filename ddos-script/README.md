#  DDoS Script - Bounded HTTP Load Test

Bounded HTTP load test for evaluating **Fail2Ban** protection on the LDAP, Backend, and Frontend services of the CineLog project.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Alpine-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-Educational-blue)

---

##  Description

This script sends a **bounded, fixed-duration HTTP flood** to a target (host + port). It is designed to test how much load each service can handle before **Fail2Ban** bans the source IP.

**Key features:**

- ✅ Accepts **host and port** as arguments (`--host`, `--port`)
- ✅ Alternative **full URL** mode (`--target`)
- ✅ Configurable **duration**, **concurrency** and **RPS**
- ✅ Bounded execution (max 300s, 500 workers, 500 RPS)
- ✅ Runs as a standalone Docker container — **outside the 3 service images**

---

## Target Services

| Service | URL | Endpoint | Protected By |
|---|---|---|---|
| Frontend (Vue + Nginx) | http://localhost:5173 | `/` | Fail2Ban `http-flood` |
| Backend (FastAPI + Nginx) | http://localhost:8001/health | `/health` | Fail2Ban `http-flood` |
| Keycloak Proxy (Nginx) | http://localhost:8081 | `/` (redirects to `/admin/`) | Fail2Ban `http-flood` + `ldap-tls` |
| LDAP TLS | ldap://openldap:636 | TLS handshake | Fail2Ban `ldap-tls` |

**Notes:**

- **Frontend:** serves the Vue SPA at `/`. Returns `index.html` (HTTP 200).
- **Backend:** exposes `/health` and `/api/movies`. The root `/` returns 404.
- **Keycloak Proxy:** `/` redirects (302) to `/admin/`, generating 2 log entries per request.
- **LDAP TLS:** the `ldap-tls` jail monitors failed TLS handshake attempts on port 636.

---

##  Usage

### With Docker (recommended)

```bash
docker build -t ddos-script .

# Test the frontend
docker run --rm --network host ddos-script --host localhost --port 5173 --duration 30

# Test the backend (uses /health endpoint)
docker run --rm --network host ddos-script --host localhost --port 8001 --duration 30 --path /health

# Test the Keycloak Proxy
docker run --rm --network host ddos-script --host localhost --port 8081 --duration 30
```

### With Python directly

```bash
python flood.py --host localhost --port 5173 --duration 30 --concurrency 100 --rps 100
```

---

##  Arguments

| Argument | Description | Default | Max |
|---|---|---|---|
| `--host` | Target host | `localhost` | - |
| `--port` | Target port | `80` | - |
| `--target` | Full URL (alternative to host/port) | - | - |
| `--path` | HTTP path | `/` | - |
| `--duration` | Seconds per target | `20` | `300` |
| `--concurrency` | Parallel workers | `40` | `500` |
| `--rps` | Max requests per second | `50` | `500` |

---

##  Steps Followed to Modify the DDoS Script

### Step 1: Analyzed the original script

The original `flood.py` had:

- Hardcoded target URLs (victim-protected, victim-unprotected).
- No command-line arguments.
- Sequential execution of both targets.

### Step 2: Added `argparse` for CLI arguments

Replaced hardcoded constants with a `parse_args()` function that accepts:

- `--host` and `--port` for the target
- `--target` for a full URL alternative
- `--duration`, `--concurrency`, `--rps` for load control
- `--path` for the request path

### Step 3: Added bounds validation

Added `validate_bounds()` to ensure:

- Duration: 1–300 seconds
- Concurrency: 1–500 workers
- RPS: 1–500 requests/second

### Step 4: Simplified to a single-target test

Removed the `TARGETS = ("victim-protected", "victim-unprotected")` loop. Now the script runs against a **single target** given by the user.

### Step 5: Added URL builder

Added `build_target_url()` which:

- Returns `args.target` if provided
- Otherwise builds `http://<host>:<port>` from `--host` and `--port`
- Auto-detects `https` for ports 443 / 8443

### Step 6: Kept the rate limiter and thread pool

Preserved the original `RateLimiter` and `ThreadPoolExecutor` logic for bounded, non-oversaturating tests.

### Step 7: Packaged as a standalone Docker image

Created a `Dockerfile` (based on `python:3.12-alpine`) so the script can run:

- **Outside** the 3 service images
- With `--network host` to reach `localhost:5173/8001/8081`

---

##  Methodology to Find the Max Load That Does NOT Crash the Service

For each target service, we ran a **3-step escalation**:

| Step | Concurrency | RPS | Duration | Purpose |
|---|---|---|---|---|
| 1 | 10 | 5 | 20s | Baseline — should NOT ban |
| 2 | 15 | 6 | 20s | Medium — may or may not ban |
| 3 | 20 | 8 | 20s | High — should ban |

**Between tests:**

1. Wait for the ban to expire OR manually unban:

   ```bash
   docker exec <container> fail2ban-client set http-flood unbanip <IP>
   ```

2. Verify the service is reachable again:

   ```bash
   curl http://localhost:<PORT>/health
   ```

**Acceptance criteria for "does not crash the service":**

- ≥ 95% of responses are HTTP 200
- Fail2Ban does **NOT** ban the source IP
- The service continues responding after the test

The **maximum RPS that does not crash** is the highest value that satisfies all 3 criteria.

---

##  Load Test Results

**See [LOAD_TEST_RESULTS.md](./LOAD_TEST_RESULTS.md)** for the full breakdown.

### Summary — Maximum Safe RPS

| Service | Port | Max Safe RPS | Fail2Ban ban threshold |
|---|---|---|---|
| Frontend | 5173 | **5 RPS** | 60 req / 10s |
| Backend | 8001 | **5 RPS** | 60 req / 10s |
| Keycloak Proxy | 8081 | **1 RPS** | 60 req / 10s |
| LDAP TLS | 636 | N/A (uses `ldap-tls` jail) | 10 attempts / 60s |

**Key finding:** The Keycloak Proxy bans faster because its `/` endpoint redirects to `/admin/`, generating **2 log entries per request**.

---

##  LDAP TLS Jail Verification

The `ldap-tls` jail was tested by injecting 12 failed TLS connection attempts to `/var/log/nginx/ldap-tls.log` with the current timestamp:

```bash
docker exec keycloak-proxy python3 -c "
from datetime import datetime
now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
with open('/var/log/nginx/ldap-tls.log', 'a') as f:
    for i in range(12):
        f.write(f'{now} ERROR Connection refused from 172.23.0.1:636\n')
print('OK: 12 lines written')
"
```

**Result:** The jail banned the IP `172.23.0.1` after 10 attempts, and created the following iptables rule:

```
-N f2b-ldap-tls
-A INPUT -p tcp -j f2b-ldap-tls
-A f2b-ldap-tls -s 172.23.0.1/32 -j REJECT --reject-with icmp-port-unreachable
-A f2b-ldap-tls -j RETURN
```

**Conclusion:** The `ldap-tls` jail provides extra protection for LDAP TLS (port 636) beyond the standard HTTP flood protection.

---

##  How to Verify Fail2Ban Banned the IP

```bash
docker exec movies-frontend fail2ban-client status http-flood
docker exec movies-backend fail2ban-client status http-flood
docker exec keycloak-proxy fail2ban-client status http-flood
docker exec keycloak-proxy fail2ban-client status ldap-tls
```

Expected output when banned:

```text
Status for the jail: http-flood
|- Filter
|  |- Currently failed: 60
|  `- File list:        /var/log/nginx/access.log
`- Actions
   |- Currently banned: 1
   |- Total banned:     1
   `- Banned IP list:   172.30.0.1
```

---

##  How to Unban an IP

```bash
docker exec movies-frontend fail2ban-client set http-flood unbanip <IP>
docker exec movies-backend fail2ban-client set http-flood unbanip <IP>
docker exec keycloak-proxy fail2ban-client set http-flood unbanip <IP>
docker exec keycloak-proxy fail2ban-client set ldap-tls unbanip <IP>
```

Or wait 10 minutes for the ban to expire automatically.

---

##  Repository Structure

```text
ddos-script/
├── flood.py                # Main script (modified with argparse)
├── Dockerfile              # Python 3.12 Alpine image
├── README.md               # This file
├── LOAD_TEST_RESULTS.md    # Full results of the load tests
└── .gitignore
```



