# 0004 – MinIO-Image von Chainguard

- Status: angenommen
- Datum: 18.11.2026

## Kontext
Die Spezifikation verlangt MinIO für das Archiv der Roh-XMLs. Stand 18.11.2026:

- das GitHub-Repository `minio/minio` ist archiviert (seit 25.04.2026) und gibt an, dass die
  Community-Edition nur noch als Quellcode verteilt wird,
- `docker pull minio/minio` schlägt fehl („repository does not exist“), `quay.io/minio/minio`
  verlangt eine Anmeldung.

## Entscheidung
Wir nutzen `cgr.dev/chainguard/minio`, ein kostenloses Image, das Chainguard aus dem MinIO-Quellcode
baut (`minio version RELEASE.2026-11-16T00-11-40Z` zum Zeitpunkt des Schreibens), fixiert per Digest
in `docker-compose.yml` und in den Integrationstests.

Die Anwendung spricht das Archiv nur über die S3-API an (boto3); der Speicher lässt sich also durch
Ändern des Endpoints austauschen (AWS S3 oder ein anderer S3-kompatibler Speicher).

## Konsequenzen
- Derselbe MinIO-Server und dieselbe S3-API wie gefordert; Dependabot kann den Digest aktualisieren.
- Stellt Chainguard das kostenlose Image ein, MinIO aus dem Quellcode bauen oder den Endpoint
  wechseln.
