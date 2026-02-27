# evidence-sdk (placeholder)

## Purpose

Experimental contribution area for shared evidence/provider SDK logic used primarily by Airflow/evidence workflows.

## Expected Inputs / Outputs

Inputs:
- provider credentials/configuration (in runtime env, not in repo)
- source telemetry/events/alerts/metrics/logs payloads

Outputs:
- normalized evidence objects that can be composed into `EvidenceBundle v1`
- adapter outputs suitable for Airflow evidence pipelines

## Hello World (placeholder)

```bash
# Example placeholder only
cd contrib/evidence-sdk
# initialize language/runtime of choice and add a simple adapter stub
```

## How to Test

- TODO: add SDK adapter unit tests.
- Ensure normalized bundle output validates against `spec/evidence-bundle.v1.schema.json`.

## Secrets

Do not add provider credentials here; keep secrets out of the repo.
