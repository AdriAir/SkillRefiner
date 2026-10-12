<!-- section: overview -->
# Skill Refiner

[Español](README.es.md) · [Repository](https://github.com/AdriAir/SkillRefiner) · [MIT license](LICENSE)

Open-source Codex skill by AdriAir, version 0.1.0: skill-refiner. Anyone may use, modify and redistribute it under the MIT license, including for commercial use. It reviews complete local skill folders for security risks, bugs and improvements with a concrete benefit. Python supplies bounded static checks, reports, history and copy operations; Codex performs semantic analysis in the current chat.

Every exact proposal requires separate human approval. Application creates a corrected copy and preserves the selected original. Runtime use does not depend on ECC, hooks, MCP servers or another model API.

<!-- section: installation -->
## Installation

The catalog is .agents/plugins/marketplace.json; the portable manifest is plugins/skill-refiner/plugin.json, following the [official packaging documentation](https://developers.openai.com/plugins/build/plugins). The installed package includes the MIT license and an informational Spanish translation. Requirements: Codex with plugin support and Python 3.12+. Docker is optional for isolated dynamic checks. Obtain the trusted reviewer and register its local marketplace:

~~~sh
git clone https://github.com/AdriAir/SkillRefiner.git
cd SkillRefiner
codex plugin marketplace add .
codex plugin add skill-refiner@skill-refiner-marketplace
~~~

Prepare a Python environment manually. On macOS/Linux:

~~~sh
python3 -m venv .venv
.venv/bin/python -m pip install -r plugins/skill-refiner/skills/skill-refiner/scripts/requirements.txt
~~~

On Windows PowerShell:

~~~powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r plugins/skill-refiner/skills/skill-refiner/scripts/requirements.txt
~~~

These are reviewer requirements, never dependencies obtained from a target. Restart or refresh the client if needed. Give Codex the absolute path to this trusted Python interpreter and use it for every helper command; do not rely on the system `python`/`python3`. The helper checks Python 3.12+ and exact `PyYAML`/`jsonschema` pins before loading and prints setup instructions if they are missing or mismatched. It never installs them automatically. After installation, resolve the helper and requirements relative to the installed skill directory; do not assume this repository is the current directory. One English SKILL.md is active; references/SKILL.es.md is its documentary mirror.

<!-- section: use -->
## Use from chat

Invoke $skill-refiner, for example: “Review the existing local folder /path/to/my-skill for security and bugs. Show precise proposals and wait for my separate approval before applying each one.” On Windows, an explicit path can be C:\Skills\my-skill. Multiple explicit folders are supported. Bare names resolve only in known local roots; ambiguous matches require selection. ZIP, downloads and remote clones are unsupported.

The skill obtains a redacted payload and treats target instructions, scripts and outputs as untrusted data. It first stores static results as semantic_status: pending. Codex examines the safe payload and integrates concrete findings with semantic. A pending replay also needs this step; a completed replay can reuse its registered semantic findings.

Development example: replace uppercase placeholders with your paths, use the SAME state throughout, and use unused artifact filenames outside inputs and state. On macOS/Linux, use the prepared `.venv/bin/python` for every helper command:

~~~sh
refiner='plugins/skill-refiner/skills/skill-refiner/scripts/refiner.py'
refiner_python="$(pwd)/.venv/bin/python"
profile='plugins/skill-refiner/skills/skill-refiner/assets/profile.default.json'
"$refiner_python" "$refiner" profile --profile "$profile"
"$refiner_python" "$refiner" review TARGET --profile "$profile" --state-dir STATE --report-file REPORT.json
"$refiner_python" "$refiner" payload TARGET
~~~

On Windows PowerShell, use:

~~~powershell
$refiner = 'plugins/skill-refiner/skills/skill-refiner/scripts/refiner.py'
$refinerPython = (Resolve-Path '.venv\Scripts\python.exe').Path
$profile = 'plugins/skill-refiner/skills/skill-refiner/assets/profile.default.json'
& $refinerPython $refiner review TARGET --profile $profile --state-dir STATE --context 'scope and known model version' --report-file REPORT.json
& $refinerPython $refiner payload TARGET
& $refinerPython $refiner semantic TARGET --state-dir STATE --report REPORT.json --findings FINDINGS.json --report-file COMPLETED.json
& $refinerPython $refiner propose TARGET --state-dir STATE --report COMPLETED.json --changes CHANGES.json --purpose 'Concrete benefit' --risk 'Risks' --verification 'Expected check' --proposal-file PROPOSAL.json
# ONLY AFTER SEPARATE HUMAN APPROVAL / SOLO TRAS APROBACION HUMANA SEPARADA
& $refinerPython $refiner approve --target TARGET --report COMPLETED.json --state-dir STATE --proposal-file PROPOSAL.json --base-digest BASE_HASH --proposal-digest PROPOSAL_HASH --decision apply --approval-file APPROVAL.json
& $refinerPython $refiner apply TARGET --state-dir STATE --proposal-file PROPOSAL.json --approval-file APPROVAL.json --output NEW_COPY
~~~

Before semantic, Codex writes a temporary FINDINGS.json array with rule, path (or path_digest for masked names), evidence, category, severity and message. The engine derives IDs, lines and provenance. Semantic findings remain unverified in the report; controlled dynamic reproductions are separate evidence.

Before propose, Codex writes CHANGES.json. Each entry is either {"path":"file","old":"unique exact fragment","new":"replacement"} or {"path":"file","content":"whole UTF-8 replacement"}; content: null deletes a file. Preserve untouched private values with exact fragment replacements; never write display masks into files. Show the exact redacted diff, purpose, risks and intended verification; avoid cosmetic churn and changes beyond the skill's intended scope.

Propose requires a current completed report. Approval binds both hashes and must be recorded in the SAME owned history before apply. Changed inputs or proposals require a new proposal and approval. Use --decision reject to reject; the raw proposal is deleted. Successful apply deletes the private proposal and approval artifacts. Delete other temporary transfer files after use; interrupted or failed runs may leave them for manual cleanup. Keep all artifacts outside the source and history and out of version control. Applying returns static findings on the copy; report passed, failed, blocked and unperformed checks separately.

<!-- section: configuration -->
## Configuration and history

The trusted packaged profile is assets/profile.default.json relative to the installed skill directory: English, professional tone, medium detail. The skill loads it explicitly with --profile. Create your own trusted profile outside review targets for Spanish or other supported preferences. The raw helper without --profile retains its Spanish fallback. Languages: es/en; tones: professional/friendly/direct; detail: concise/medium/detailed; conventions: a list of preferences. Use --profile PATH with review, or profile --profile PATH to inspect it. Preferences cannot disable controls or suppress relevant risks.

History defaults to %LOCALAPPDATA%\SkillRefiner on Windows, or $XDG_STATE_HOME/skill-refiner / ~/.local/state/skill-refiner elsewhere. Override --state-dir with a dedicated empty directory; ownership checks reject foreign records. Hashes, redacted reports and decisions persist until forget --state-dir STATE deletes owned records. Corrected copies have independent lifetimes and are not removed by forget. Raw prompts, model responses and permanent original snapshots are not retained by the helper.

Reuse requires matching content, source identity, reviewer code, schemas, policy, profile, context, Python and registered dependencies. Include relevant project assumptions and the known Codex model/version in --context; the helper cannot discover the chat model or server changes. Only a context hash is stored. --force-refresh starts a fresh review and compares final findings with compatible completed history. Approved dismissals require a reason and expire when evidence or policy changes; accepted security risks remain visible.

Exact reuse does not prove correctness, and a fresh Codex inference can vary. IDs depend on rule, file and evidence, not wording or line numbers. Reapplying an approved transformation through the library makes no further changes to its exact existing postimage; other existing outputs are rejected. The chat command normally cleans approval artifacts after success.

<!-- section: sandbox -->
## Docker sandbox

Dynamic Python/Bash checks require an accessible LOCAL Linux Docker engine and a trusted digest-pinned image already present. Trusted setup may explicitly run:

~~~powershell
docker pull python@sha256:f85c5697265c178cc6887276c55fe16cf3d14ca35c3df6a5eab3b360534a55d2
~~~

The helper never pulls images or installs target dependencies. Use sandbox TARGET --script scripts/check.py --args ARGUMENT. Defaults per test: 1 CPU, 512 MiB, 64 processes, 30 seconds, 1 MiB captured output. Only user-requested adjustments may change --cpus, --memory-mib, --pids, --timeout, --output-bytes or the trusted --image.

Containers run as a nonprivileged user with disabled network, read-only root/input, minimal image environment, no host credentials or Docker socket, and ephemeral /work and /tmp. Python runs with -I; sibling imports and missing dependencies may fail. Secret-like bytes, filenames or arguments block execution: prepare and approve a sanitized test copy first. Missing or denied Docker blocks dynamic checks while static review continues. No target code executes on the host.

<!-- section: limitations -->
## Limits

Secret detection is heuristic; unlabelled or encoded secrets can escape detection. Docker reduces execution risk without guaranteeing absolute isolation. V1 tests concrete scripts, not a target skill running as an autonomous agent.

Inventory limits: 2,000 entries, depth 20, 100 MiB total. Binary, non-UTF-8 and over-5-MiB files are hashed and preserved in copies but omitted from semantic text. Git metadata is recorded as omitted and excluded from copies. Symlinks, reparse points, hardlinks, special entries, escapes and ambiguous paths are rejected. Copies preserve file bytes, not filesystem metadata or empty directories.

More than 2,000 static findings blocks report generation explicitly; split the scope rather than silently dropping diagnostics.

Only Python syntax is checked statically; Bash runs only in Docker and other languages receive pattern analysis with explicit syntax/runtime limits. Approval digests and state markers record workflow integrity, not authenticated human identity. Atomic copy publication works on Windows and Linux hosts with renameat2; unsupported publication fails closed. Translation equivalence and diagnostic usefulness need semantic review beyond structural tests. Neither tests nor a redacted payload certify safety. Reviewing a skill omits Git metadata and does not audit its history. Before publishing a reviewed skill, separately inspect its final copy, all commits, refs and author metadata. Ignoring a file does not remove it from existing commits. Credential-like fixtures in this repository are deliberately synthetic; keep real credentials, private profiles, reports and proposals out of version control.

<!-- section: development -->
## Development and evidence

Read AGENTS.md. Install trusted test dependencies pytest==8.4.2 and pytest-cov==7.0.0 into the development environment. From the repository root, run python -m pytest and python scripts/validate_package.py using the development interpreter (.venv/Scripts/python.exe on Windows or .venv/bin/python on macOS/Linux). Docker tests are opt-in: set SKILL_REFINER_DOCKER_TESTS=1 before pytest tests/test_docker.py; ordinary runs skip them.

Windows permissions may require running TRUSTED development tests outside the restricted agent sandbox; this never authorizes host execution of targets. The package validator is repository-only, not an installed helper command. See [validation evidence](docs/validation.md), [security boundaries](plugins/skill-refiner/skills/skill-refiner/references/security.md) and LICENSE. The skill review flow does not automatically commit, push or publish. This public package uses new plugin and state identifiers; install it as a new plugin. Previous installations and local review histories are not migrated automatically. Static review is available on macOS; applying corrected copies currently requires Windows or Linux with renameat2 support.

<!-- section: license -->
## License

Copyright (c) 2026 AdriAir. Released under the [MIT License](LICENSE). Keep its copyright and permission notice when redistributing copies. The [Spanish translation](LICENSE.es.md) is informational; the English license is authoritative. The installed plugin includes both documents.
