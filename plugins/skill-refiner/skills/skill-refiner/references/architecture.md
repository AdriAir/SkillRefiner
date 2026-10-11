<!-- section: overview -->
# Architecture

The package has one portable `plugin.json`, the discoverable English `SKILL.md`, a Spanish mirror, `agents/openai.yaml`, local Python helper code under `scripts/`, schemas, references, and tests. The repository root owns packaging and verification policy.

<!-- section: interfaces -->
## Interfaces

The helper commands are `review`, `payload`, `semantic`, `propose`, `approve`, `apply`, `dismiss`, `forget`, `sandbox`, and `profile`. The root `scripts/validate_package.py` is a developer tool, not an installed helper command. The root `pyproject.toml` owns Python dependencies and test configuration.
