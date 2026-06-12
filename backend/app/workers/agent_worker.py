import asyncio
import datetime
import json

import redis
from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings
from app.core.db import AsyncSessionLocal

MAX_CONCURRENT_JOBS = 20

# 1. Removed semaphore logic from inside the worker
async def execute_agent(redis_client, job):
    stream_id = job["stream_id"]
    try:
        payload = {
            "type": "data",
            "data": f"Pretend agent execution is happening @ time {datetime.datetime.now()}"
        }
        await redis_client.publish(f"stream_{stream_id}", json.dumps(payload))
        await asyncio.sleep(5)  # Simulate time taken for agent to execute
    except Exception as e:
        error_payload = {
            "type": "error",
            "data": str(e)
        }
        await redis_client.publish(f"stream_{stream_id}", json.dumps(error_payload))

async def main():
    # 2. Use a proper ConnectionPool to handle concurrent calls safely
    pool = ConnectionPool.from_url(settings.REDIS_URL, decode_responses=True, max_connections=50,  socket_timeout=10)
    redis_client = Redis(connection_pool=pool)

    # The semaphore is placed in the main loop to control flow
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

    try:
        while True:
            # 3. Wait for an execution slot to become free BEFORE fetching a job
            await semaphore.acquire()
            try:
                result = await redis_client.brpop("agent_jobs_queue", timeout=5)
            except redis.exceptions.TimeoutError:
                # No job found within timeout, release the slot and continue waiting
                semaphore.release()
                continue
            except redis.exceptions.ConnectionError:
                semaphore.release()
                await asyncio.sleep(0.5)
                continue
            if result:
                _, job_data = result
                job = json.loads(job_data)

                # 4. Create the background task
                task = asyncio.create_task(execute_agent(redis_client, job))

                # 5. Release the semaphore slot automatically when this specific task finishes
                task.add_done_callback(lambda t: semaphore.release())
            else:
                # No job found, release the slot immediately and rest briefly
                semaphore.release()
                await asyncio.sleep(0.1)
    finally:
        # Clean up connection resources on exit
        await redis_client.aclose()
        await pool.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
