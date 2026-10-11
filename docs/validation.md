<!-- section: overview -->
# Validation evidence

Public-release preparation for Skill Refiner 0.1.0 on 2026-10-11. Host: macOS, Python 3.12.14, Codex CLI 0.162.0-alpha.17.2. Trusted test dependencies were installed with explicit permission into an isolated temporary environment. Results below describe observed checks and their limits, not certification. Author and license holder: AdriAir; license: MIT.

<!-- section: evidence -->
## Current verification

- Identity/state migration was developed with failing tests before implementation. Public package, XDG state and Windows state tests passed after the change. Secret-prefix regression tests also failed against the original detector and passed after hardening it.
- Full suite with canonical temporary paths (TMPDIR=/private/tmp): **102 passed, 8 failed, 5 skipped**. Measured main-process refinerlib coverage: **76%**. The original HEAD tested under the same conditions had **82 passed, the same 8 failed, 5 skipped**; no new failing test was introduced.
- Seven existing failures come from macOS lacking the supported atomic copy-publication primitive; one comes from macOS normalizing Unicode filenames before a collision can be observed. Neither behavior was weakened to make tests pass. Applying corrected copies is supported on Windows and Linux with renameat2, and fails closed on unsupported hosts. This run does not validate publication on those supported platforms.
- Eighteen focused regression cases passed for detection, redacted semantic payloads and pre-Docker blocking of synthetic GitHub, GitLab, Slack, Stripe, temporary AWS and multiline DSA private-key formats. The DSA tests check the body marker as well as the whole key to avoid vacuous JSON-escaping assertions. The detector remains heuristic.
- The package validator passed: one discoverable skill, valid local references/contracts, nine bilingual document pairs, MIT manifest, AdriAir authorship and identical root/installed license copies. git diff --check passed.
- A separate verifier registered the local marketplace and installed skill-refiner in a temporary CODEX_HOME using the real Codex CLI. The installed helper ran by absolute path and loaded its packaged profile as English/professional/medium. Usual Codex settings were not modified.
- README and SKILL mirrors received an independent review of meaning, commands, profile selection, approval controls and limitations. Matching section IDs alone does not establish semantic equivalence.

<!-- section: audit -->
## Git and publication audit

At audit time the GitHub repository was private and advertised only main, matching the local root commit a322038f; no remote tags were advertised. The local clone was not shallow. Review covered every available object: **78 objects (1 commit, 21 trees, 56 blobs)**, all four local refs, commit metadata/messages and three reflog entries. git fsck found no errors or dangling/unreachable objects. No alternate object stores, replace refs, grafts, submodules or LFS content were present.

No real credential was identified. Credential-like assignments, JWTs and PEM blocks in the historical blobs were synthetic fixtures or detector patterns. Content scans found no private email addresses, host-specific home paths, internal URLs or credential files. The single commit's author/committer metadata does contain a personal email, and its tree retains the former branding and restrictive license. These historical records are separate from the cleaned working tree and still need an explicitly approved history replacement before the strict public-release requirement is met.

Two local Codex snapshot refs contain a .DS_Store binary beyond the branch tree. It showed no email, host path, URL or secret markers. It is ignored in the current tree and must not be published. Reflogs and local snapshot refs are not included in an ordinary push of main; never use a mirror push for this release.

Proposed history cleanup: replace the sole root commit with the reviewed public tree, use the owner's verified GitHub noreply identity, and update only main with an explicit expected-old-SHA lease. Commit/history replacement and push require separate human approval. Keep the repository private until the advertised history is checked again. Rewriting refs does not guarantee deletion from other clones or GitHub caches; see [GitHub's removal documentation](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).

<!-- section: limitations -->
## Blocked and unperformed checks

Docker's local daemon was not running even after an authorized access check. The five opt-in cases produced one pass and four failures because the Linux engine was inaccessible; they do not validate container execution or isolation in this run. No daemon was started and no image was downloaded.

No dedicated external secret scanner was installed. The audit combined all-object enumeration, pattern/content inspection, metadata review and manual classification of synthetic matches; unknown or encoded secrets can evade these checks. No guarantee of absolute confidentiality is made.

Not performed: fresh Windows/Linux host tests, installation in usual Codex settings, desktop/browser QA, autonomous target-agent execution, commit, history rewrite, push or change of repository visibility. Current working-tree preparation does not by itself remove anything from already-pushed commits. Private artifacts and original inputs must remain outside version control; corrected copies have independent lifetimes.
