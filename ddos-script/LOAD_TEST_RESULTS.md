#  Load Test Results

Environment: Docker Desktop on Windows, local machine (Docker Desktop 4.x, WSL2 backend).

---

##  Test Configuration

| Parameter | Value |
|---|---|
| **Tool** | `flood.py` (this repository) |
| **Mode** | Docker container with `--network host` |
| **Targets** | Frontend, Backend, Keycloak Proxy |
| **Fail2Ban threshold (http-flood)** | `maxretry = 60`, `findtime = 10s` |
| **Fail2Ban threshold (ldap-tls)** | `maxretry = 10`, `findtime = 60s` |

---

##  Summary Table — Maximum Safe Load

| Service | Port | Max RPS (no ban) | RPS that triggers ban | Fail2Ban jail |
|---|---|---|---|---|
| Frontend (Vue + Nginx) | 5173 | **5 RPS** | 6 RPS | `http-flood` |
| Backend (FastAPI + Nginx) | 8001 | **5 RPS** | 6 RPS | `http-flood` |
| Keycloak Proxy (Nginx) | 8081 | **1 RPS** | 2 RPS | `http-flood` + `ldap-tls` |
| LDAP TLS (port 636) | — | N/A (not HTTP) | 10 attempts in 60s | `ldap-tls` |

**Conclusion:** The maximum RPS that does NOT crash each service and does NOT trigger a Fail2Ban ban is **5 RPS for the Frontend and Backend**, and **1 RPS for the Keycloak Proxy**.

---

##  FRONTEND (Vue + Nginx + Fail2Ban) — Port 5173

### Test 1: Baseline (5 RPS, 20s) — ✅ SAFE

```bash
docker run --rm --network host ddos-script --host localhost --port 5173 --duration 20 --concurrency 10 --rps 5
```

**Result:**
- Total requests: **98**
- OK (200): **98**
- Failed: **0**
- **% Failed: 0%**
- **Banned: NO** ✅

**Conclusion:** 5 RPS is safe for the Frontend.

### Test 2: Medium load (6 RPS, 20s) — ⚠️ BAN

```bash
docker run --rm --network host ddos-script --host localhost --port 5173 --duration 20 --concurrency 15 --rps 6
```

**Result:**
- Total requests: **117**
- OK (200): **61**
- Failed: **56**
- **% Failed: 47%**
- **Banned: YES** (after ~61 successful requests)

**Conclusion:** 6 RPS triggers a ban.

### Test 3: High load (50 RPS, 30s) — ⚠️ BAN

```bash
docker run --rm --network host ddos-script --host localhost --port 5173 --duration 30 --concurrency 40 --rps 50
```

**Result:**
- Total requests: **660**
- OK (200): **76**
- Failed: **584**
- **% Failed: 88%**
- **Banned: YES** (after ~2 seconds)

**Conclusion:** 50 RPS bans immediately.

### Summary Table — Frontend

| RPS | Total | OK | Failed | % Failed | Banned |
|---|---|---|---|---|---|
| **5** | 98 | 98 | 0 | **0%** | ❌ NO |
| 6 | 117 | 61 | 56 | 47% | ✅ YES |
| 8 | 155 | 62 | 93 | 60% | ✅ YES |
| 50 | 660 | 76 | 584 | 88% | ✅ YES |

** MAXIMUM SAFE LOAD: 5 RPS**

---

##  BACKEND (FastAPI + Nginx + Fail2Ban) — Port 8001

**IMPORTANT:** The backend exposes only `/health` and `/api/movies`. The root `/` returns 404. Use `--path /health`.

### Test 1: Baseline (5 RPS, 20s, `/health`) — ✅ SAFE

```bash
docker run --rm --network host ddos-script --host localhost --port 8001 --duration 20 --concurrency 10 --rps 5 --path /health
```

**Result:**
- Total requests: **98**
- OK (200): **98**
- Failed: **0**
- **% Failed: 0%**
- **Banned: NO** ✅

**Conclusion:** 5 RPS is safe for the Backend.

### Test 2: Medium load (6 RPS, 20s, `/health`) — ⚠️ BAN

```bash
docker run --rm --network host ddos-script --host localhost --port 8001 --duration 20 --concurrency 15 --rps 6 --path /health
```

**Result:**
- Total requests: **117**
- OK (200): **63**
- Failed: **54**
- **% Failed: 46%**
- **Banned: YES** (after ~63 successful requests)

**Conclusion:** 6 RPS triggers a ban.

### Summary Table — Backend

| RPS | Total | OK | Failed | % Failed | Banned |
|---|---|---|---|---|---|
| **5** | 98 | 98 | 0 | **0%** | ❌ NO |
| 6 | 117 | 63 | 54 | 46% | ✅ YES |

** MAXIMUM SAFE LOAD: 5 RPS**

---

##  KEYCLOAK PROXY (Nginx + Fail2Ban) — Port 8081

**IMPORTANT:** The `/` endpoint redirects (HTTP 302) to `/admin/`, generating **2 log entries per request**. This halves the effective RPS threshold.

### Test 1: Baseline (1 RPS, 20s) — ✅ SAFE

```bash
docker run --rm --network host ddos-script --host localhost --port 8081 --duration 20 --concurrency 3 --rps 1
```

**Result:**
- Total requests: **20**
- OK (200): **20**
- Failed: **0**
- **% Failed: 0%**
- **Banned: NO** ✅

**Conclusion:** 1 RPS is safe for the Keycloak Proxy.

### Test 2: Medium load (2 RPS, 20s) — ⚠️ BAN

```bash
docker run --rm --network host ddos-script --host localhost --port 8081 --duration 20 --concurrency 5 --rps 2
```

**Result:**
- Total requests: **40**
- OK (200): **20**
- Failed: **20**
- **% Failed: 50%**
- **Banned: YES** (after ~20 successful requests)

**Conclusion:** 2 RPS triggers a ban.

### Test 3: High load (5 RPS, 20s) — ⚠️ BAN

```bash
docker run --rm --network host ddos-script --host localhost --port 8081 --duration 20 --concurrency 10 --rps 5
```

**Result:**
- Total requests: **99**
- OK (200): **23**
- Failed: **76**
- **% Failed: 76%**
- **Banned: YES** (after ~23 successful requests)

**Conclusion:** 5 RPS bans quickly.

### Why does the Keycloak Proxy ban faster?

The Keycloak Proxy serves the Keycloak Admin Console. The endpoint `/` **redirects (HTTP 302)** to `/admin/`:

```
GET /               → 302 Found
GET /admin/         → 200 OK
```

**Each request from the flood script generates 2 log entries** in `/var/log/nginx/access.log`. Fail2Ban counts both, effectively **doubling** the request rate.

**Mathematical verification:**

| Script RPS | Log entries/s | Requests / 10s | Against threshold (60) |
|---|---|---|---|
| 1 RPS | 2 | 20 | ✅ Safe |
| 2 RPS | 4 | 40 | ⚠️ Close |
| 5 RPS | 10 | 100 | ❌ Ban |

### Summary Table — Keycloak Proxy

| RPS | Total | OK | Failed | % Failed | Banned |
|---|---|---|---|---|---|
| **1** | 20 | 20 | 0 | **0%** | ❌ NO |
| 2 | 40 | 20 | 20 | 50% | ✅ YES |
| 5 | 99 | 23 | 76 | 76% | ✅ YES |

** MAXIMUM SAFE LOAD: 1 RPS**

---

##  LDAP TLS (Port 636) — Jail `ldap-tls`

The Keycloak Proxy has an **extra jail** called `ldap-tls` that monitors failed LDAP TLS connection attempts on port **636**.

### Test: Simulate failed TLS connections

Since the LDAP server runs in a separate container, its logs are not directly visible to the proxy. We simulated 12 failed TLS connection attempts by injecting log lines into `/var/log/nginx/ldap-tls.log` with **current timestamps**:

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

**Result:**

```
Status for the jail: ldap-tls
|- Filter
|  |- Currently failed: 0
|  |- Total failed:     12       ← 12 attempts detected
|  `- File list:        /var/log/nginx/ldap-tls.log
`- Actions
   |- Currently banned: 1         ← IP banned
   |- Total banned:     1
   `- Banned IP list:   172.23.0.1    ← Full IP captured
```

**iptables rule created:**

```
-N f2b-ldap-tls
-A INPUT -p tcp -j f2b-ldap-tls
-A f2b-ldap-tls -s 172.23.0.1/32 -j REJECT --reject-with icmp-port-unreachable
-A f2b-ldap-tls -j RETURN
```

### Jail Configuration

```ini
[ldap-tls]
enabled = true
port = 636,389
filter = ldap-tls
logpath = /var/log/nginx/ldap-tls.log
maxretry = 10
findtime = 60s
bantime = 30m
```

**Conclusion:** The LDAP TLS jail correctly bans IPs after **10 failed attempts within 60 seconds**, with a **30-minute ban**.

---

##  Test Methodology

### Setup

1. **Start all services:**

   ```bash
   cd ldap-keycloak-oauth2-lab && docker compose up -d
   cd movies-backend && docker compose up -d
   cd movies-dashboard && docker compose up -d
   ```

2. **Verify Fail2Ban is running on each container:**

   ```bash
   docker exec movies-frontend fail2ban-client status
   docker exec movies-backend fail2ban-client status
   docker exec keycloak-proxy fail2ban-client status
   ```

   Expected: `Number of jail: 1` (frontend, backend) or `2` (proxy: http-flood + ldap-tls).

### Testing Procedure

For each service, we ran a **3-step escalation** to find the safe threshold:

| Step | RPS | Duration | Purpose |
|---|---|---|---|
| 1 | 5 | 20s | Baseline — should NOT ban |
| 2 | 6 | 20s | Find ban threshold |
| 3 | 50 | 20-30s | Confirm ban triggers quickly |

**For the Keycloak Proxy**, the values were different because of the redirect:

| Step | RPS | Duration | Purpose |
|---|---|---|---|
| 1 | 1 | 20s | Baseline — should NOT ban |
| 2 | 2 | 20s | Find ban threshold |
| 3 | 5 | 20s | Confirm ban triggers quickly |

### Between tests

```bash
# Check ban status
docker exec <container> fail2ban-client status http-flood

# Unban if needed
docker exec <container> fail2ban-client set http-flood unbanip <IP>
```

### Acceptance Criteria

A load test is considered **"safe"** when:

- ✅ ≥ **95% of responses are HTTP 200**
- ✅ Fail2Ban does **NOT** ban the source IP
- ✅ The service **continues responding** after the test

The **maximum RPS that does not crash** is the highest value that satisfies all 3 criteria.

---

##  FINAL RESULTS

| Service | Port | Max Safe RPS | Ban Trigger | Recommendation |
|---|---|---|---|---|
| **Frontend** | 5173 | **5 RPS** | 6 RPS | Safe up to 5 RPS from a single IP |
| **Backend** | 8001 | **5 RPS** | 6 RPS | Safe up to 5 RPS from a single IP |
| **Keycloak Proxy** | 8081 | **1 RPS** | 2 RPS | Safe up to 1 RPS from a single IP |
| **LDAP TLS** | 636 | N/A | 10 attempts / 60s | Jail confirmed working |

---

##  Key Findings

1. **Fail2Ban works as expected** — all 3 jails (`http-flood` × 3 + `ldap-tls` × 1) successfully banned IPs.

2. **The default threshold (60 req/10s) provides strong protection:**
   - Any flood above 6 RPS from a single IP is quickly blocked.
   - This is well within the "abusive" range — legit users rarely exceed 1-2 RPS.

3. **The Keycloak Proxy bans faster** because of the `/` → `/admin/` redirect (2x log entries).

4. **Timestamps matter** — logs older than `findtime` (60s) are ignored by Fail2Ban. All injected test logs must use the **current timestamp**.

5. **The LDAP TLS jail works** with a stricter threshold (10 attempts / 60s) for port 636, providing an **extra layer of protection**.

---

##  Appendix — Commands Reference

### Run a flood test

```bash
docker run --rm --network host ddos-script --host localhost --port <PORT> --duration 20 --concurrency 10 --rps 5 [--path /health]
```

### Check Fail2Ban status

```bash
docker exec <container> fail2ban-client status http-flood
docker exec keycloak-proxy fail2ban-client status ldap-tls
```

### Unban an IP

```bash
docker exec <container> fail2ban-client set http-flood unbanip <IP>
```

### View iptables rules

```bash
docker exec <container> iptables -S | grep f2b
```

### Test filter regex manually

```bash
docker exec <container> fail2ban-regex /var/log/nginx/access.log /etc/fail2ban/filter.d/http-flood.conf
```