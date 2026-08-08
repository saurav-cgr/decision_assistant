from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from fastapi import UploadFile

UPLOAD_CHUNK_BYTES = 64 * 1024


class StoredObjectTooLarge(Exception):
    pass


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size: int
    checksum: str
    local_path: Path


class ObjectStorage(Protocol):
    async def put_upload(
        self,
        *,
        key: str,
        upload: UploadFile,
        max_bytes: int,
    ) -> StoredObject: ...

    def local_path(self, key: str) -> Path: ...

    def delete(self, key: str) -> None: ...


class LocalFileStorage:
    """Filesystem backend implementing same logical-key boundary as S3."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    async def put_upload(
        self,
        *,
        key: str,
        upload: UploadFile,
        max_bytes: int,
    ) -> StoredObject:
        destination = self.local_path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = sha256()
        size = 0
        try:
            with destination.open("wb") as output:
                while chunk := await upload.read(UPLOAD_CHUNK_BYTES):
                    size += len(chunk)
                    if size > max_bytes:
                        raise StoredObjectTooLarge
                    digest.update(chunk)
                    output.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()

        return StoredObject(
            key=key,
            size=size,
            checksum=digest.hexdigest(),
            local_path=destination,
        )

    def local_path(self, key: str) -> Path:
        destination = (self._root / key).resolve()
        if not destination.is_relative_to(self._root):
            raise ValueError("Object key escapes storage root")
        return destination

    def delete(self, key: str) -> None:
        self.local_path(key).unlink(missing_ok=True)
