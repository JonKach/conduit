from lxml.html.builder import B
from _asyncio import Future
from app.core.config import settings
from fastapi_cloud_cli.commands.env import delete
import asyncio
from fastapi import APIRouter, Depends
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from pydantic.networks import EmailStr
from sqlmodel import col, select

from app.api.deps import get_current_active_superuser
from app.core.db import AsyncSessionLocal
from app.models import Agent, Message, Thread
from app.utils import generate_test_email, send_email
from gcloud.aio.storage import Storage, Bucket, Blob

router = APIRouter(prefix="/utils", tags=["utils"])


@router.post(
    "/test-email/",
    dependencies=[Depends(get_current_active_superuser)],
    status_code=201,
)
def test_email(email_to: EmailStr) -> Message:
    """
    Test emails.
    """
    email_data = generate_test_email(email_to=email_to)
    send_email(
        email_to=email_to,
        subject=email_data.subject,
        html_content=email_data.html_content,
    )
    return Message(message="Test email sent")


@router.get("/health-check/")
def health_check() -> bool:
    return True


async def delete_langgraph_threads(
    thread_ids: list[str], 
    connection_pool, 
    gcs_storage,
) -> None:
    """
    Delete all thread checkpoints for a list of thread IDs and cleanup GCS files.
    """
    if not thread_ids:
        return

    checkpointer = AsyncPostgresSaver(connection_pool)

    thread_sem = asyncio.Semaphore(20)

    async def delete_thread_files(thread_id: str):
        async with thread_sem:
            try:
                await checkpointer.adelete_thread(thread_id)
            except Exception as e:
                print(f"Failed to delete thread {thread_id}: {e}")

    await asyncio.gather(*(delete_thread_files(tid) for tid in thread_ids), return_exceptions=True)

    bucket = Bucket(gcs_storage, settings.GCS_BUCKET_NAME)

    gcs_search_tasks = [bucket.list_blobs(prefix=f"agent-files/{tid}/") for tid in thread_ids]

    search_results = await asyncio.gather(*gcs_search_tasks, return_exceptions=True)

    blob_sem = asyncio.Semaphore(20)

    async def _safe_delete_blob(blob_name: str, thread_id: str):
        async with blob_sem:
            try:
                await gcs_storage.delete(settings.GCS_BUCKET_NAME, blob_name)
            except Exception as e:
                print(f"Failed to delete blob {blob_name} for thread {thread_id}: {e}")

    delete_file_tasks = []

    for thread_id, result in zip(thread_ids, search_results, strict=True):
        if isinstance(result, Exception):
            print(f"Failed to fetch documents for thread {thread_id}: {result}")
            continue

        for item in result:
            delete_file_tasks.append(_safe_delete_blob(item, thread_id))

    if delete_file_tasks:
        await asyncio.gather(*delete_file_tasks, return_exceptions=True)

async def search_and_delete(search_tasks, store: AsyncPostgresStore, resources: list) -> None:

    search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

    sem = asyncio.Semaphore(20)

    async def _safe_delete(namespace, key):
        async with sem:
            try:
                await store.adelete(namespace, key)
            except Exception as e:
                print(f"Failed to delete ({namespace}, {key}): {e}")

    delete_tasks = []
    for resource, result in zip(resources, search_results, strict=True):
        if isinstance(result, Exception):
            print(f"Failed to fetch documents for resource {resource}: {result}")
            continue

        for item in result:
            delete_tasks.append(_safe_delete(item.namespace, item.key))

    if delete_tasks:
        await asyncio.gather(*delete_tasks)

async def delete_agent_store(agent_ids: list[str], connection_pool, gcs_storage) -> None:
    """
    Delete all long-term store entries (skills & memories) for a list of agent IDs.
    """

    if not agent_ids:
        return

    store = AsyncPostgresStore(connection_pool)

    search_tasks = [
        store.asearch((agent_id,), limit=1000) for agent_id in agent_ids
    ]

    delete_profile_picture_tasks = [
        gcs_storage.delete(settings.GCS_BUCKET_NAME, f"agent-profiles/{agent_id}") for agent_id in agent_ids
    ]

    await search_and_delete(search_tasks, store, agent_ids)

    if delete_profile_picture_tasks:
        await asyncio.gather(*delete_profile_picture_tasks)

async def delete_user_memories(user_id: str, connection_pool) -> None:
    """
    Delete all long-term store entries for a specific user ID.
    """

    store = AsyncPostgresStore(connection_pool)

    matching_namespaces = await store.alist_namespaces(suffix=(user_id,))

    search_tasks = [
        store.asearch(namespace, limit=1000) for namespace in matching_namespaces
    ]

    await search_and_delete(search_tasks, store, matching_namespaces)
