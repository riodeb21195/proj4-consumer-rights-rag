from collections.abc import Iterator

import pytest
from testcontainers.community.minio import MinioContainer

from rag.store.object_store import RawStore

# Same images as docker-compose.yml. MinIO's Docker Hub image is gone; Chainguard builds it from
# source (see docs/decisions/0004-object-storage.md).
MINIO_IMAGE = (
    "cgr.dev/chainguard/minio"
    "@sha256:7618b82bba99aadd77fcf59eb6cfd89b4b8b8e01ac796c474d57a1c1abf17e79"
)


@pytest.fixture(scope="session")
def minio() -> Iterator[MinioContainer]:
    with MinioContainer(image=MINIO_IMAGE) as container:
        yield container


@pytest.fixture
def raw_store(minio: MinioContainer, request: pytest.FixtureRequest) -> RawStore:
    cfg = minio.get_config()
    bucket = f"test-{request.node.name.lower().replace('_', '-')}"[:60]
    store = RawStore.from_settings(
        f"http://{cfg['endpoint']}", cfg["access_key"], cfg["secret_key"], bucket
    )
    store.ensure_bucket()
    return store
