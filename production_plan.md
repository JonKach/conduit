# Production Readiness Plan

A scan of the repo covering missing frontend coverage, critical bugs, email
server setup, and a transition plan to AWS (monolith) with CI/CD.

## 1. Missing Frontend Coverage

Coverage is actually very good — almost every backend endpoint has a UI. The
real gaps:

- **Skill file preview is missing.** `GET /agents/{id}/skills/{skill_name}`
  (skill content) is generated in the SDK but never called anywhere. You can
  upload and delete skill files, but never *see* what's in one after
  uploading it. Worth a "view" action in `EditAgent.tsx`'s skill list.
- **Token validity is never checked on boot.** `useAuth.ts:14` gates the
  whole app purely on `localStorage.getItem("access_token") !== null` — it
  never calls the existing `POST /login/test-token` endpoint. Combined with
  bug #5 below, this means an expired session doesn't bounce you to
  `/login`, it just makes the app quietly stop working.
- **Dead code to delete before shipping:** `backend/app/api/routes/mcp.py`
  is 17KB, 100% commented out, and not even registered in `main.py` — pure
  clutter. `private.py`'s open `POST /private/users/` (no auth at all) is
  correctly gated behind `ENVIRONMENT == "local"`, but it's one
  misconfigured env var away from being an open user-creation endpoint in
  prod — worth a startup assertion, not just a conditional mount.
- Everything else (agents, threads, chat, admin, user settings, password
  recovery pages, marketplace) is fully wired end-to-end.

## 2. Critical Bugs (fix before launch)

**Critical:**

- **No rate limiting on `/login` at all** (`login.py:20`) — every other
  router has a `RateLimiter` dependency; login doesn't. Unlimited password
  brute-force and reset-email spam today.
- **Path traversal in thread file upload/delete.** `gcs_backend.py:157-160`
  builds the GCS object key by just `lstrip("/")`-ing the filename — a
  filename like `../<other_thread_id>/SKILL.md` escapes the thread's own
  prefix. Same issue in `delete_file` (`threads.py:290-295`), which
  interpolates the raw path param. This lets one user write into or delete
  another user's/thread's files.
- **Password hashes hitting your logs.** `crud.py:55` does
  `print("db_user:", db_user)` on every login attempt, and the default
  SQLModel repr includes `hashed_password`. Every login candidate's hash
  lands in stdout/log aggregation.

**High:**

- **Expired tokens return 403, not 401** (`deps.py:44-47`), so
  `main.tsx`'s (correctly-scoped) "log out on 401" handler never fires —
  after the 60-minute token expiry, the app just silently breaks instead of
  bouncing to login.
- **Password recovery is non-functional and leaks account existence.**
  `send_email` hard-asserts `settings.emails_enabled` (`utils.py:39`); with
  SMTP unset (as it is today) this throws, so `/password-recovery/{email}`
  500s for real emails but 200s for fake ones — the exact
  account-enumeration protection the code comments claim to prevent is
  broken. (More in §3.)
- **Worker robustness:** `thread_status:{id}` is set to `RUNNING` with no
  TTL and only cleared on the manual-stop path (`agent_worker.py:91` vs
  `203`) — a crashed job leaves it stuck forever, and a bad JSON message on
  the queue kills the whole consumer loop (unguarded `json.loads` outside
  any try). A dropped job (lock already held) never emits an `error` SSE
  event, so the browser just hangs.

**Medium:** `delete_file` swallows non-404 GCS errors and reports success
anyway; `/utils/get-tools/` and `/utils/health-check/` have no auth or rate
limiting; `SECRET_KEY` defaults to a random-per-process value (breaks JWT
validation the moment you run >1 backend replica — directly relevant once
you're on ECS/ASG with multiple instances).

## 3. Email Server

Currently **scaffolding only, never connected to a real provider.** `.env`
ships SMTP settings empty; only the dev `mailcatcher` compose service ever
receives mail. In production, any code path that tries to send email
(password recovery, admin test-email) throws instead of sending.

To fix, since you're heading to AWS:

1. **Amazon SES** — verify your sending domain, request production access
   (SES starts in sandbox, capped to verified recipients only), set up
   DKIM/SPF via Route 53.
2. Point the existing settings at it:
   `SMTP_HOST=email-smtp.<region>.amazonaws.com`, port 587 with TLS, SMTP
   credentials from an IAM user scoped to `ses:SendEmail` (or use the SES
   API directly instead of SMTP — less code churn to just fill in
   settings, though).
3. Fix `send_email` so a delivery failure logs and degrades gracefully
   instead of raising an unhandled exception into a 500 — and make sure
   `/password-recovery/{email}` always returns the same response regardless
   of whether the address exists or the send succeeded, closing the
   enumeration hole.

## 4. AWS Migration (Monolith)

Current stack: docker-compose (db, redis, backend, agent-worker,
frontend/nginx, Traefik) on a single VPS. For a monolith on AWS, the
lowest-friction path that preserves that shape:

- **Compute:** EC2 (or an Auto Scaling Group of 1-2) running the same
  Docker Compose file, behind an **Application Load Balancer** with an
  **ACM** certificate — this directly replaces Traefik/Let's Encrypt with
  minimal rework, and keeps backend + `agent-worker` co-located exactly as
  today. If you'd rather go AWS-native over "keep the VPS shape," ECS
  Fargate with two task definitions (api, worker) sharing the same image is
  the alternative, at the cost of more moving pieces.
- **Database:** RDS for PostgreSQL, Multi-AZ if you want HA. One important
  detail: your Postgres already does double duty — it's both the app's
  SQLModel database *and* LangGraph's checkpointer/store
  (`langgraph_store_setup.py`). No change needed there, just point both
  connection strings at the RDS endpoint.
- **Redis:** ElastiCache for Redis, replacing the self-hosted
  `redis:7.4-alpine` container. It's used as both a pub/sub bus for SSE
  streaming and the job queue for `agent-worker` — ElastiCache handles both
  fine.
- **File storage:** You're currently 100% on GCS (`gcs_backend.py`, agent
  files, profile pictures) via a JSON credentials blob in an env var. For a
  full AWS move you'd port that to S3 — same shape (per-thread/agent
  prefix, presigned URLs instead of GCS signed URLs), but it's a real
  rewrite of `gcs_backend.py`'s async storage layer, not a config change.
  Alternatively, keep GCS as-is and accept the one cross-cloud dependency —
  plenty of AWS shops do this for object storage specifically.
- **Secrets:** AWS Secrets Manager (or SSM Parameter Store) for
  `SECRET_KEY`, DB/Redis passwords, SMTP creds,
  `GOOGLE_APPLICATION_CREDENTIALS_JSON`, API keys — replacing the current
  single hand-managed `.env` on the server. This also forces a fix for the
  random-per-process `SECRET_KEY` bug, since it'll be pinned to one real
  value.
- **Frontend:** it's a static Vite SPA behind nginx today — move it to
  **S3 + CloudFront** regardless of the "monolith" framing for the
  backend; there's no reason to keep serving static assets from a compute
  instance. Only catch: `VITE_API_URL` is currently baked in as a Docker
  *build arg*, so the image (and now the S3 bundle) is
  environment-specific — you'll want your CI to build once per
  environment, not build-once-promote-everywhere.
- **Logging:** replace the `print()`-as-logging pattern (found throughout
  the worker and `crud.py`) with the standard `logging` module and ship to
  CloudWatch Logs — you'll want this before the log-leaking-password-hashes
  bug becomes a compliance problem in CloudWatch instead of a local file.

## 5. GitHub CI/CD → AWS

Today: `deploy-production.yml`/`deploy-staging.yml` run on **self-hosted
runners installed on the VPS itself**, and just do
`docker compose build && docker compose up -d` locally on that machine — no
registry, no promotion, no rollback path. This whole model goes away in an
AWS setup.

Recommended replacement (keeping your existing trigger model — push-to-
`master` for staging, GitHub release for production):

1. **Switch to GitHub-hosted runners** and authenticate to AWS via **OIDC**
   (`aws-actions/configure-aws-credentials` with `role-to-assume`) — no
   long-lived AWS keys in repo secrets.
2. **Build & push** backend/worker image (same image, different command,
   matching your current YAML-anchor reuse) to **ECR**.
3. **Run migrations** as a one-off task before cutover — an ECS `RunTask`
   (Fargate) or an SSM `send-command` invocation of `alembic upgrade head`
   on the EC2 instance, replacing the current `prestart` compose service.
4. **Deploy:**
   - EC2/Compose path: SSM `send-command` to pull the new image tag and
     re-run `docker compose up -d` on the instance — this is the direct
     replacement for "self-hosted runner does it locally," just pushed
     from GitHub instead.
   - ECS path: `aws ecs update-service --force-new-deployment` (or the
     `amazon-ecs-deploy-task-definition` action) for zero-downtime rolling
     deploys.
5. **Frontend:** build the static bundle in CI, `aws s3 sync` to the
   bucket, `aws cloudfront create-invalidation`.
6. Keep your existing `test-docker-compose.yml`, `playwright.yml`, and
   `test-backend.yml` as PR gates unchanged — they're infra-agnostic and
   don't need to change for the AWS move.

## Suggested Order of Operations

1. Fix the critical/high bugs in §2 first (rate limiting, path traversal,
   log leakage, 401/403, worker robustness) — these matter regardless of
   hosting provider and are cheap to fix now.
2. Wire up SES for email (§3) — password recovery is currently broken in
   any real deployment.
3. Stand up RDS + ElastiCache + Secrets Manager, decide EC2-Compose vs ECS
   for compute, and get one environment (staging) running end-to-end on
   AWS before touching DNS.
4. Decide on GCS-vs-S3 for file storage (this is the biggest "real work"
   item if you go full-AWS).
5. Swap CI/CD to the OIDC + ECR + SSM/ECS deploy model, cut staging over
   first, then production.
