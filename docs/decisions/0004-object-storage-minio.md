# 0004 – MinIO image from Chainguard

- Status: accepted
- Date: 2026-11-18

## Context
The spec requires MinIO for the raw XML archive. On 2026-11-18:

- the GitHub repository `minio/minio` is archived (since 2026-04-25) and states that the community
  edition is distributed as source code only,
- `docker pull minio/minio` fails ("repository does not exist"), `quay.io/minio/minio` requires
  authentication.

## Decision
Use `cgr.dev/chainguard/minio`, a free image that Chainguard builds from the MinIO source
(`minio version RELEASE.2026-11-16T00-11-40Z` at the time of writing), pinned by digest in
`docker-compose.yml` and the integration tests.

The application talks to the archive only through the S3 API (boto3), so the storage backend
can be swapped (AWS S3, another S3-compatible store) by changing the endpoint.

## Consequences
- Same MinIO server and S3 API as required; Dependabot can bump the digest.
- If Chainguard stops publishing the free image, build MinIO from source or switch the endpoint.
