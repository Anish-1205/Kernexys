# Kernexys reference model runtime

This component is a deterministic, CPU-only sentiment classifier used to prove
Kernexys deployment behavior. It intentionally stays small: platform behavior,
not model quality, is the project focus.

The image build argument `MODEL_VERSION` bakes either `v1` or `v2` into the OCI
artifact. At startup the process rejects a conflicting
`KERNEXYS_MODEL_VERSION`, preventing a declared model version from silently
running the wrong built-in weights.

Endpoints are `/health/live`, `/health/ready`, `/v1/infer`, and `/metrics`.
