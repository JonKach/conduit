<p align="center">
  <img width="1059" height="441" alt="Screenshot 2026-10-15 at 10 59 49 AM" src="https://github.com/user-attachments/assets/b6d89450-4dd7-4771-8c12-97f4ac79ea8f" />
</p>


# Conduit

A platform for building and sharing AI agents. Users create agents with a system prompt, tools, and skill files; chat with them in threads supporting multimodal file uploads, long-term user memory, and task-level planning; and publish them to a marketplace where others can add them to their own list and chat with them instantly.

## Motivations 

Conduit was built as a full-stack and agentic engineering learning project. The project was intended to build experience with production-level best practices in backend, frontend, DevOps, and Applied AI. Today, a demo version is online at [conduitplatform.com](conduitplatform.com).

## Stack

- **Backend:** FastAPI, SQLModel (async), Alembic, PostgreSQL
- **Agents:** LangGraph Deepagents with Postgres checkpointing and long-term store, Tavily web search
- **Streaming:** An asynchronous agent worker consumes jobs from Redis and streams results back to the browser over SSE
- **Storage:** Google Cloud Storage, AWS RDS
- **Frontend:** React 19, TypeScript, Vite, TanStack Router + Query, Tailwind CSS, shadcn/ui
- **Infra:** Docker Compose, Traefik, per-user rate limiting backed by Redis

## Project layout

```
backend/
  app/api/routes/     REST endpoints (agents, threads, users, login)
  app/api/core/       Database setup, security, and configuration
  app/workers/        Agent worker that runs LangGraph jobs off the Redis queue
  app/gcs_backend.py  Custom deepagents filesystem backend on top of GCS, tailored for async
  ...
frontend/
  src/routes/         File-based routes via TanStack Router
  src/components/     Feature components (ui/ is shadcn)
  src/client/         API client generated from the backend OpenAPI schema
  ...
```

*Testing files exist throughout the repository and in GitHub workflows. 

## Running locally

1. Copy in `.env` values: Postgres, Redis, `SECRET_KEY`, `GOOGLE_API_KEY`, `TAVILY_API_KEY`, `GCS_BUCKET_NAME` and `GOOGLE_APPLICATION_CREDENTIALS_JSON`.
2. Start the stack:

   ```bash
   docker compose watch
   ```

3. Open the frontend at http://localhost:5173 and the API docs at http://localhost:8000/docs.

After changing backend models or routes, regenerate the frontend client with `bash scripts/generate-client.sh`.

Built on the [FastAPI full-stack template](https://github.com/fastapi/full-stack-fastapi-template).
