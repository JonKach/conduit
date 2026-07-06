"""A thread-scoped Google Cloud Storage backend for LangChain deep agents.

Key ideas
---------
1. GCS is a FLAT namespace. There are no real folders. "Hierarchy" is just a
   prefix convention on the object name. So we store every file at:

       gs://{bucket}/{root_prefix}/{thread_id}/{path}

   Listing a thread's files is a single prefix list call. No subfolders are
   ever created, nothing is slow, and a thread with 10k files costs the same
   per-write as a thread with 1 file.

2. Thread isolation is resolved AT CALL TIME from the LangGraph run config via
   `get_config()["configurable"]["thread_id"]` (exactly how the built-in
   StoreBackend resolves its namespace). One shared backend instance stays
   correctly scoped across concurrent threads because `get_config()` reads a
   context var that is unique per invocation.
"""

from __future__ import annotations

import base64
import binascii
import mimetypes
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath

from langgraph.config import get_config

# Reuse deepagents' own classification so the blocks we build at message time
# are identical to what the read_file tool would emit mid-loop.
from deepagents.backends.utils import _get_file_type

from deepagents.backends.protocol import (
    BackendProtocol,
    EditResult,
    FileData,
    FileInfo,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)
from deepagents.backends.utils import (
    create_file_data,
    file_data_to_string,
    grep_matches_from_files,
    perform_string_replacement,
    slice_read_response,
    _glob_search_files,
)

# Classify by extension FIRST (matching deepagents' read_file), so images like
# .jpg/.png/.webp/.gif/.heic — plus audio/video/pdf — are always treated as
# binary regardless of byte content. Byte-sniffing is only the fallback for
# unknown extensions.
_TEXT_SUFFIXES = {".txt", ".md", ".json", ".csv", ".py", ".html", ".xml", ".yaml", ".yml", ".log"}


def _guess_content_type(path: str) -> str:
    """image/jpeg for .jpg/.jpeg, image/png for .png, etc. Mirrors read_file."""
    return mimetypes.guess_type("file" + PurePosixPath(path).suffix)[0] or "application/octet-stream"


def _looks_binary(path: str, raw: bytes) -> bool:
    # 1) Extension is authoritative when deepagents recognizes it.
    ftype = _get_file_type(path)            # "text"/"image"/"audio"/"video"/"file"
    if ftype != "text":
        return True                          # image/png, image/jpeg, pdf, ... -> binary
    lower = path.lower()
    if any(lower.endswith(s) for s in _TEXT_SUFFIXES):
        return False
    # 2) Unknown extension -> fall back to sniffing the bytes.
    if b"\x00" in raw[:4096]:
        return True
    try:
        raw.decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True


class GCSBackend(BackendProtocol):
    """Stores deep-agent files in a GCS bucket, namespaced per thread_id.

    Args:
        bucket: an initialized ``google.cloud.storage.Bucket`` (or any object
            exposing ``blob(name)`` and ``list_blobs(prefix=...)``).
        root_prefix: top-level prefix under which all threads live.
        thread_id: optional explicit override; if omitted, resolved per-call
            from the LangGraph run config.
    """

    def __init__(self, bucket, root_prefix: str = "agent-files", thread_id: str | None = None):
        self._bucket = bucket
        self._root = root_prefix.strip("/")
        self._explicit_thread_id = thread_id

    # ---- thread scoping -------------------------------------------------
    def _thread_id(self) -> str:
        if self._explicit_thread_id is not None:
            return self._explicit_thread_id
        try:
            cfg = get_config()
            tid = cfg.get("configurable", {}).get("thread_id")
        except Exception:
            tid = None
        if not tid:
            # Never write to the bucket root if scoping fails — fail loud.
            raise RuntimeError(
                "GCSBackend could not resolve thread_id from run config. "
                "Invoke the agent with config={'configurable': {'thread_id': ...}}."
            )
        return str(tid)

    def _key(self, agent_path: str) -> str:
        """Map an agent path like '/media/cat.png' -> '{root}/{thread}/media/cat.png'."""
        rel = agent_path.lstrip("/")
        return f"{self._root}/{self._thread_id()}/{rel}"

    def _prefix(self) -> str:
        return f"{self._root}/{self._thread_id()}/"

    def _agent_path(self, key: str) -> str:
        """Inverse of _key: strip the '{root}/{thread}/' prefix, return '/...'. """
        return "/" + key[len(self._prefix()):]

    # ---- low-level IO ---------------------------------------------------
    def _read_bytes(self, agent_path: str) -> bytes | None:
        blob = self._bucket.blob(self._key(agent_path))
        if not blob.exists():
            return None
        return blob.download_as_bytes()

    def _file_data(self, agent_path: str) -> FileData | None:
        raw = self._read_bytes(agent_path)
        if raw is None:
            return None
        if _looks_binary(agent_path, raw):
            return create_file_data(base64.b64encode(raw).decode("ascii"), encoding="base64")
        return create_file_data(raw.decode("utf-8"), encoding="utf-8")

    def _write_bytes(self, agent_path: str, raw: bytes, content_type: str | None = None) -> None:
        blob = self._bucket.blob(self._key(agent_path))
        # Derive image/jpeg, image/png, application/pdf, ... from the extension
        # so signed-URL fetches carry the right Content-Type header.
        ct = content_type or _guess_content_type(agent_path)
        blob.upload_from_string(raw, content_type=ct)

    # ---- BackendProtocol surface ---------------------------------------
    def ls(self, agent_path: str) -> LsResult:
        prefix = self._prefix()
        sub = agent_path.lstrip("/")
        if sub:
            prefix = f"{prefix}{sub.rstrip('/')}/"
        entries: list[FileInfo] = []
        for blob in self._bucket.list_blobs(prefix=prefix):
            info: FileInfo = {"path": self._agent_path(blob.name)}
            if getattr(blob, "size", None) is not None:
                info["size"] = blob.size
            updated = getattr(blob, "updated", None)
            if updated is not None:
                info["modified_at"] = updated.isoformat() if hasattr(updated, "isoformat") else str(updated)
            entries.append(info)
        return LsResult(entries=entries)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        fd = self._file_data(file_path)
        if fd is None:
            return ReadResult(error=f"File not found: {file_path}")
        sliced = slice_read_response(fd, offset, limit)
        if isinstance(sliced, ReadResult):
            return sliced
        # slice_read_response returns the formatted string; hand back FileData
        # so the middleware renders binary/text consistently.
        return ReadResult(file_data=fd)

    def write(self, file_path: str, content: str) -> WriteResult:
        # `content` is always a str from the tool layer; persist as utf-8 bytes.
        self._write_bytes(file_path, content.encode("utf-8"), content_type="text/plain; charset=utf-8")
        return WriteResult(path=file_path)

    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> EditResult:
        fd = self._file_data(file_path)
        if fd is None:
            return EditResult(error=f"File not found: {file_path}")
        text = file_data_to_string(fd)
        result = perform_string_replacement(text, old_string, new_string, replace_all)
        if isinstance(result, str):  # error message
            return EditResult(error=result)
        new_text, occurrences = result
        self._write_bytes(file_path, new_text.encode("utf-8"), content_type="text/plain; charset=utf-8")
        return EditResult(path=file_path, occurrences=occurrences)

    # ---- optional: grep/glob via in-memory snapshot of the thread -------
    def _snapshot(self) -> dict[str, FileData]:
        files: dict[str, FileData] = {}
        for blob in self._bucket.list_blobs(prefix=self._prefix()):
            ap = self._agent_path(blob.name)
            fd = self._file_data(ap)
            if fd is not None:
                files[ap] = fd
        return files

    def grep(self, pattern: str, path: str | None = None, glob: str | None = None) -> GrepResult:
        return grep_matches_from_files(self._snapshot(), pattern, path, glob)

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        matches = _glob_search_files(self._snapshot(), pattern, path)
        # helper returns a formatted string of paths; normalize to FileInfo list
        paths = [ln for ln in matches.splitlines() if ln.strip()] if isinstance(matches, str) else []
        return GlobResult(matches=[{"path": p} for p in paths])

    # ---- developer-facing helper (not an agent tool) -------------------
    def put_upload(self, agent_path: str, raw: bytes, content_type: str | None = None) -> str:
        """Call this from your upload endpoint to stage a user file for a thread.

        Returns the agent-visible path (e.g. '/uploads/cat.png').
        """
        self._write_bytes(agent_path, raw, content_type=content_type)
        return agent_path

    def generate_signed_url(self, agent_path: str, *, minutes: int = 15, method: str = "GET") -> str:
        """Mint a short-lived URL the model's provider can fetch server-side.

        Note for GCE / Cloud Run / GKE: the default compute service account has
        no private key, so v4 signing needs the IAM Credentials API. Either run
        under a service-account JSON key, or pass `service_account_email=` plus
        `access_token=` to `generate_signed_url` (requires the
        `iam.serviceAccounts.signBlob` permission). With a JSON key the call
        below works as-is.
        """
        blob = self._bucket.blob(self._key(agent_path))
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=minutes),
            method=method,
        )


# ============================================================================
# Message-time adapter
# ----------------------------------------------------------------------------
# "Message-time blocks" = converting a thread's stored uploads into the content
# blocks the model consumes AT INVOKE TIME, so it sees them on this turn —
# rather than waiting for the agent to call read_file mid-loop.
# ============================================================================

# The fixed universe of media block types deepagents can render (everything
# except plain "text"). Used to validate requested subsets.
_MEDIA_TYPES = ("image", "audio", "video", "file")

# Default subset to INLINE at message time. Images only, because that's the one
# media kind essentially every multimodal model accepts. Override per call (or
# change this constant) if your model also takes audio/video/PDF "file" blocks.
DEFAULT_INJECT_TYPES = ("image", "file")


def _resolve_types(types: tuple[str, ...] | None) -> tuple[str, ...]:
    if types is None:
        return DEFAULT_INJECT_TYPES
    unknown = set(types) - set(_MEDIA_TYPES)
    if unknown:
        raise ValueError(f"Unknown media types {sorted(unknown)}; allowed: {_MEDIA_TYPES}")
    return types


def _block_for_path(scoped: "GCSBackend", agent_path: str, mode: str, minutes: int) -> dict | None:
    """Build one content block for a single file path, or None if not media."""
    ftype = _get_file_type(agent_path)                          # deepagents' own classifier
    if ftype == "text":
        return None
    mime = mimetypes.guess_type("file" + PurePosixPath(agent_path).suffix)[0] or "application/octet-stream"
    if mode == "url":
        block: dict = {"type": ftype, "url": scoped.generate_signed_url(agent_path, minutes=minutes)}
        if ftype != "image":                              # non-image url blocks need explicit mime
            block["mime_type"] = mime
        return block
    raw = scoped._read_bytes(agent_path)
    if raw is None:
        return None
    return {"type": ftype, "base64": base64.b64encode(raw).decode("ascii"), "mime_type": mime}


def media_blocks_for_paths(
    bucket,
    thread_id: str,
    agent_paths: list[str],
    *,
    root_prefix: str = "agent-files",
    mode: str = "base64",
    minutes: int = 15,
    types: tuple[str, ...] | None = None,
) -> list[dict]:
    """Build content blocks for an EXPLICIT list of newly-attached paths.

    Only the paths you pass are turned into blocks — nothing is auto-discovered.
    This is the key to NOT re-sending files on follow-up turns.

    `types` defaults to DEFAULT_INJECT_TYPES (images). Pass a subset of
    _MEDIA_TYPES to include audio/video/PDF "file" blocks for models that
    support them.
    """
    allowed = _resolve_types(types)
    scoped = GCSBackend(bucket, root_prefix=root_prefix, thread_id=thread_id)
    blocks: list[dict] = []
    for agent_path in agent_paths:
        if _get_file_type(agent_path) not in allowed:
            continue
        block = _block_for_path(scoped, agent_path, mode, minutes)
        if block is not None:
            blocks.append(block)
    return blocks


def build_user_message(
    bucket,
    thread_id: str,
    text: str,
    attached_agent_paths: list[str] | None = None,
    *,
    mode: str = "base64",
    root_prefix: str = "agent-files",
    minutes: int = 15,
    types: tuple[str, ...] | None = None,
) -> dict:
    """Assemble a user turn, embedding ONLY files attached to THIS message.

    - First turn (user just uploaded files): pass `attached_paths=[...]` -> the
      message carries those media blocks so the model sees them immediately.
    - Follow-up turn (no new uploads): pass nothing -> a plain text message.
      The files are still in GCS; if the agent needs to look again it calls
      `read_file`, which re-reads fresh bytes from GCS (so nothing expires and
      old images don't ride along on every turn).

    mode:
      - "base64"    : self-contained, survives replay from the checkpoint, never
                      expires. Recommended for anything that gets persisted.
      - "url"       : signed URL — leaner, BUT it persists in history and will
                      expire; only safe if you strip it before the next turn.
      - "reference" : embed NO media; append a one-line text note of the paths
                      and let the agent read_file on demand (leanest, costs one
                      tool round-trip for the first view).
    """
    attached_agent_paths = attached_agent_paths or []

    if mode == "reference":
        scoped = GCSBackend(bucket, root_prefix=root_prefix, thread_id=thread_id)
        ls_result = scoped.ls("/")  # list all files for this thread
        if ls_result.entries:
            text = text + "\n\nThe following files are available in the thread's media store (/media/). Use read_file to view them if relevant and not already loaded into context.\n" + "\n".join(
                f"- /media{entry['path']}" for entry in ls_result.entries
            )
        return {"role": "user", "content": text}

    blocks = media_blocks_for_paths(
        bucket, thread_id, attached_agent_paths,
        root_prefix=root_prefix, mode=mode, minutes=minutes, types=types,
    )
    if not blocks:
        return {"role": "user", "content": text}   # pure text follow-up
    return {"role": "user", "content": [{"type": "text", "text": text}, *blocks]}
