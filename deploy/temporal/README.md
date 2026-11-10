# Temporal on minikube

This directory holds everything needed to run **Temporal only** in Kubernetes.
The FastAPI server, Temporal worker, LiveKit, and the voice agent keep running
on the host; see the root README for why.

```
deploy/temporal/
  namespace.yaml       Kubernetes namespace (owned by kubectl)
  postgres.yaml        PostgreSQL 16 Service + StatefulSet (owned by kubectl)
  networkpolicy.yaml   Only Temporal chart pods may reach PostgreSQL (owned by kubectl)
  values.yaml          Configuration for the Temporal Helm chart (owned by Helm)
```

## Ownership: Helm vs. this repo

| Object | Created by | Source of truth |
| --- | --- | --- |
| `temporal` namespace | `kubectl apply -f namespace.yaml` | `namespace.yaml` |
| `temporal-postgres` Secret | `scripts/temporal-up.sh`, once | cluster only, never Git |
| `temporal-postgres` Service/StatefulSet/PVC | `kubectl apply -f postgres.yaml` | `postgres.yaml` |
| `temporal-postgres` NetworkPolicy | `kubectl apply -f networkpolicy.yaml` | `networkpolicy.yaml` |
| frontend / history / matching / worker | Helm | `values.yaml` + chart |
| Web UI | Helm | `values.yaml` + chart |
| schema and namespace Jobs | Helm hooks | chart |
| Temporal `default` namespace | Helm hook | `values.yaml` (`server.config.namespaces`) |

The Temporal workloads are **not** hand-written YAML. They are rendered by the
official chart from `values.yaml`, so upgrading the chart is a one-line change
instead of a manifest merge. This repo therefore stores configuration, not
generated output.

The chart itself is downloaded at install time rather than vendored:

```bash
helm repo add temporal https://temporalio.github.io/helm-charts
```

`helm.temporal.io` does not resolve on every network; the GitHub Pages mirror
serves the same signed index and is what `scripts/temporal-up.sh` uses.

## Pinned versions

| Component | Version | Pinned in |
| --- | --- | --- |
| Temporal Helm chart | `1.8.0` | `TEMPORAL_CHART_VERSION` in `scripts/temporal-up.sh` |
| Temporal server | `1.32.2` | chart `appVersion` (tracked by the chart version) |
| PostgreSQL | `16.15-alpine` | `postgres.yaml` image tag |
| Kubernetes (minikube) | server `v1.37.0` on minikube `v1.39.0` | minikube |

Bump the chart version deliberately, then re-run `make temporal-up` and check
`helm -n temporal history` plus the Temporal UI. A one-off override is fine:

```bash
TEMPORAL_CHART_VERSION=1.9.0 make temporal-up
```

## Secrets

Nothing sensitive is committed. `postgres.yaml` only reads an existing Secret:

```yaml
env:
  - name: POSTGRES_PASSWORD
    valueFrom:
      secretKeyRef:
        name: temporal-postgres
        key: password
```

On first run, `scripts/temporal-up.sh` generates a 32-character password with
`openssl rand -hex 16` and creates the Secret. Subsequent runs detect the
existing Secret and leave it alone.

The Temporal chart consumes the same Secret through `existingSecret` and
`secretKey` in `values.yaml`, so there is a single copy of the credential.

Rotating the password requires recreating the PostgreSQL volume, because the
password is written into the database during `initdb`. For this disposable
local setup, the simplest path is:

```bash
./scripts/temporal-down.sh --purge
make temporal-up
```

To inspect the credential locally (without printing it to shell history):

```bash
kubectl -n temporal get secret temporal-postgres \
  -o jsonpath='{.data.password}' | base64 --decode
```

## Network boundary

`networkpolicy.yaml` selects the PostgreSQL pods and allows inbound `5432`
only from pods labelled `app.kubernetes.io/instance=temporal`. Every other
ingress is denied by the policy.

NetworkPolicy objects are only enforced when the CNI implements the API.
minikube v1.39 (Kubernetes v1.37) with its default kindnet CNI does enforce
them here. The policy was checked in both directions against the live cluster.

From an unlabelled pod, the database is unreachable:

```bash
kubectl -n default run netpol-check --restart=Never \
  --image=postgres:16.15-alpine --command -- \
  sh -c 'pg_isready -h temporal-postgres.temporal.svc.cluster.local -p 5432 -t 5'

# temporal-postgres.temporal.svc.cluster.local:5432 - no response
# exit=2
```

From a pod carrying the chart's instance label, it is reachable:

```bash
kubectl -n temporal run netpol-allow --restart=Never \
  --labels=app.kubernetes.io/instance=temporal \
  --image=postgres:16.15-alpine --command -- \
  pg_isready -h temporal-postgres -p 5432 -t 5

# temporal-postgres:5432 - accepting connections
# exit=0
```

If you switch to a different CNI or driver, re-run the first check. If it
succeeds, the policy is not being enforced and you should either enable a
policy-capable CNI (`minikube start --cni=calico` on a disposable cluster) or
treat the boundary as documentation only.

## Validation

Local:

```bash
helm pull temporal/temporal --version 1.8.0 --untar --untardir /tmp/charts
helm lint /tmp/charts/temporal -f deploy/temporal/values.yaml
helm template temporal /tmp/charts/temporal \
  --namespace temporal -f deploy/temporal/values.yaml > /tmp/rendered.yaml
kubectl apply --dry-run=client -f deploy/temporal/namespace.yaml \
  -f deploy/temporal/postgres.yaml -f deploy/temporal/networkpolicy.yaml
```

CI (`.github/workflows/ci.yml`) runs the same checks on every push: unit
tests, `helm lint`, `helm template`, and `kubeconform` on both the raw
manifests and the rendered chart output.

## Lifecycle

```bash
make temporal-up                       # namespace, Secret, Postgres, policy, chart, port-forwards
make temporal-down                     # stop port-forwards only
./scripts/temporal-down.sh --purge     # uninstall the release and delete the namespace/volume
```

`--purge` deletes the namespace, which also deletes the generated Secret and
the PostgreSQL persistent volume. The next `make temporal-up` starts from an
empty database.
