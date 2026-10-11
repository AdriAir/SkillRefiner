<!-- section: overview -->
# Workflow

The durable review flow is resolve, snapshot, static review, semantic review, propose, approve, and apply. Explicit target paths are required; ambiguous targets pause for clarification.

<!-- section: evidence -->
## Evidence

Static rule matches are reported separately from confirmed reproducible bugs. Semantic or LLM findings remain unverified unless repository evidence and controlled reproduction support them. A matching file or phrase proves existence only.

<!-- section: approval -->
## Approval

Each exact proposal is approved in the same chat and binds both base and proposal digests. Any change invalidates approval. Applying always writes a new output outside the source and never commits.
