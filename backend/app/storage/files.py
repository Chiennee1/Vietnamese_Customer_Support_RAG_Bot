from pathlib import Path
from typing import Protocol
from uuid import uuid4

from anyio import to_thread


class FileStorage(Protocol):
    async def save(self, key: str, content: bytes) -> None: ...

    async def read(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...


class LocalFileStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        target = (self.root / key).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError("Storage key escapes configured root")
        return target

    async def save(self, key: str, content: bytes) -> None:
        target = self._resolve(key)
        await to_thread.run_sync(self._write_atomic, target, content)

    async def read(self, key: str) -> bytes:
        return await to_thread.run_sync(self._resolve(key).read_bytes)

    async def delete(self, key: str) -> None:
        target = self._resolve(key)
        await to_thread.run_sync(self._delete_if_exists, target)

    @staticmethod
    def _write_atomic(target: Path, content: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4()}.tmp")
        try:
            temporary.write_bytes(content)
            temporary.replace(target)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _delete_if_exists(target: Path) -> None:
        if target.exists():
            target.unlink()
