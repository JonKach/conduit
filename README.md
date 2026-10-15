# Conduit

A platform for building and sharing AI agents. Users create agents with a system prompt, tools and skill files, chat with them in threads (including file uploads), and publish them to a marketplace where others can add them to their own list.

## Stack

- **Backend:** FastAPI, SQLModel (async), Alembic, PostgreSQL
- **Agents:** LangGraph / deepagents with Postgres checkpointing and long-term store, Gemini models, Tavily web search
- **Streaming:** a separate agent worker consumes jobs from Redis and streams results back to the browser over SSE
- **Storage:** Google Cloud Storage for thread files and agent profile pictures
- **Frontend:** React 19, TypeScript, Vite, TanStack Router + Query, Tailwind CSS, shadcn/ui
- **Infra:** Docker Compose, Traefik, per-user rate limiting backed by Redis

## Project layout

```
backend/
  app/api/routes/     REST endpoints (agents, threads, users, login)
  app/workers/        agent worker that runs LangGraph jobs off the Redis queue
  app/gcs_backend.py  deepagents filesystem backend on top of GCS
frontend/
  src/routes/         file-based routes
  src/components/     feature components (ui/ is shadcn)
  src/client/         API client generated from the backend OpenAPI schema
```

## Running locally

1. Copy `.env` values: Postgres, Redis, `SECRET_KEY`, `GOOGLE_API_KEY`, `TAVILY_API_KEY`, `GCS_BUCKET_NAME` and `GOOGLE_APPLICATION_CREDENTIALS_JSON`.
2. Start the stack:

   ```bash
   docker compose watch
   ```

3. Open the frontend at http://localhost:5173 and the API docs at http://localhost:8000/docs.

After changing backend models or routes, regenerate the frontend client with `bash scripts/generate-client.sh`.

Built on the [FastAPI full-stack template](https://github.com/fastapi/full-stack-fastapi-template).
