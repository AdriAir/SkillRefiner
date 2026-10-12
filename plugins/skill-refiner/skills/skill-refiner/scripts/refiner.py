"""Local command line adapter for the Skill Refiner libraries.

The CLI intentionally only moves bounded JSON between a human-operated chat
workflow and the deterministic local helpers.  It never executes target code.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from refinerlib.runtime import runtime_issues


_RUNTIME_ISSUES = runtime_issues()
if _RUNTIME_ISSUES:
    sys.stderr.write("Skill Refiner cannot start:\n")
    for _issue in _RUNTIME_ISSUES:
        sys.stderr.write("- " + _issue + "\n")
    sys.stderr.write(
        "Use Python 3.12+ and install the pinned requirements into that interpreter:\n"
        "  <python-3.12-interpreter> -m pip install -r "
        + str(Path(__file__).resolve().parent / "requirements.txt")
        + "\n"
        "Replace <python-3.12-interpreter> with the absolute Python 3.12+ executable path.\n"
        "Then configure Codex to use that same absolute interpreter path.\n"
    )
    raise SystemExit(2)

from refinerlib.analysis import analyze, semantic_payload
from refinerlib.common import RefinerError, canonical, ensure_outside, read_json, redact, redact_tree, reject_links
from refinerlib.contracts import validate_contract
from refinerlib.history import (
    complete_review,
    default_state_dir,
    dismiss,
    forget,
    record_decision,
    require_approved_decision,
    require_completed_report,
    review,
    validate_profile,
)
from refinerlib.proposals import apply, approve, propose, public_proposal
from refinerlib.sandbox import DEFAULT_IMAGE, SandboxConfig, run_test
from refinerlib.snapshot import inventory, resolve_targets, prepared_inventory


MAX_JSON_BYTES = 100 * 1024 * 1024


def _path(value: str) -> Path:
    return reject_links(Path(value))


def _read_json(path: str):
    item = _path(path)
    if not item.is_file() or item.stat().st_size > MAX_JSON_BYTES:
        raise RefinerError("JSON input is missing or exceeds the supported size")
    try:
        return read_json(item)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RefinerError("Invalid JSON input") from error


def _write_new_json(path: str, value, *, source: Path | None = None, state: Path | None = None) -> Path:
    target = _path(path)
    if source is not None:
        ensure_outside(target, source)
    if state is not None:
        ensure_outside(target, state)
    if target.exists():
        raise RefinerError("Refusing to overwrite an existing artifact")
    target.parent.mkdir(parents=True, exist_ok=True)
    target = reject_links(target)
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(target, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical(value).decode("utf-8") + "\n")
    except FileExistsError as error:
        raise RefinerError("Refusing to overwrite an existing artifact") from error
    return target


def _state(value: str | None) -> Path:
    return _path(value) if value else default_state_dir()


def _targets(values: list[str]) -> list[Path]:
    # Explicit local paths do not need discovery.  Besides avoiding an
    # unnecessary scan of user-managed plugin caches, this keeps a malformed
    # unrelated installed skill from preventing a direct review.
    explicit = all(Path(value).is_absolute() or value.startswith(("./", ".\\")) or "/" in value or "\\" in value for value in values)
    targets = resolve_targets(values, [] if explicit else None)
    if not targets:
        raise RefinerError("At least one target is required")
    return targets


def _load_profile(path: str | None):
    return validate_contract("profile", validate_profile(_read_json(path) if path else None))


def _emit(value) -> None:
    sys.stdout.write(canonical(redact_tree(value)).decode("utf-8") + "\n")


def command_review(args):
    state = _state(args.state_dir)
    sources = _targets(args.target)
    for source in sources:
        ensure_outside(state, source)
    profile = _load_profile(args.profile)
    if args.report_file and len(sources) != 1:
        raise RefinerError("--report-file supports one target")
    result = [validate_contract("report", review(source, state, profile, args.context or "", args.force_refresh)) for source in sources]
    for source, report in zip(sources, result):
        if args.report_file:
            _write_new_json(args.report_file, report, source=source, state=state)
    return result[0] if len(result) == 1 else {"reports": result}


def command_semantic(args):
    source = _targets([args.target])[0]
    state = _state(args.state_dir)
    report = _read_json(args.report)
    findings = _read_json(args.findings)
    if not isinstance(findings, list):
        raise RefinerError("Findings must be a JSON array")
    validate_contract("report", report)
    # Semantic candidates intentionally omit generated identifiers, line
    # numbers and provenance.  `complete_review` validates concrete evidence
    # against the snapshot and derives those trusted fields.
    result = validate_contract("report", complete_review(source, report, state, findings))
    if args.report_file:
        _write_new_json(args.report_file, result, source=source, state=state)
    return result


def command_payload(args):
    source = _targets([args.target])[0]
    return semantic_payload(prepared_inventory(source))


def command_propose(args):
    source = _targets([args.target])[0]
    state = _state(args.state_dir)
    ensure_outside(state, source)
    report = _read_json(args.report)
    validate_contract("report", report)
    require_completed_report(source, state, report)
    changes = _read_json(args.changes)
    if not isinstance(changes, list):
        raise RefinerError("Changes must be a JSON array")
    snapshot = inventory(source)
    proposal = validate_contract("proposal", propose(source, changes, args.purpose, args.risk, args.verification))
    _write_new_json(args.proposal_file, proposal, source=source, state=state)
    return public_proposal(proposal, snapshot)


def command_approve(args):
    state = _state(args.state_dir)
    source = _targets([args.target])[0]
    ensure_outside(state, source)
    report = _read_json(args.report)
    validate_contract("report", report)
    require_completed_report(source, state, report)
    proposal_path = _path(args.proposal_file)
    approval_path = _path(args.approval_file)
    ensure_outside(proposal_path, source)
    ensure_outside(proposal_path, state)
    ensure_outside(approval_path, source)
    ensure_outside(approval_path, state)
    if args.decision == "apply" and approval_path.exists():
        raise RefinerError("Refusing to overwrite an existing artifact")
    proposal = _read_json(args.proposal_file)
    validate_contract("proposal", proposal)
    if inventory(source).digest != proposal["base_digest"]:
        raise RefinerError("Proposal is outdated for the current source")
    approval = approve(proposal, args.base_digest, args.proposal_digest, args.decision, args.reason or "")
    # The proposal itself is untrusted; use only its digest-bound metadata in state.
    record = {
        "proposal_id": approval["proposal_id"], "base_digest": approval["base_digest"],
        "proposal_digest": approval["proposal_digest"], "decision": approval["decision"],
        "reason": approval["reason"], "timestamp": approval["timestamp"],
    }
    if not state.exists():
        raise RefinerError("State must be created by review or propose before approval")
    record_decision(state, record)
    if args.decision == "reject":
        proposal_path.unlink(missing_ok=True)
        return {key: value for key, value in approval.items() if key != "approval_digest"}
    validate_contract("approval", approval)
    _write_new_json(args.approval_file, approval, state=state)
    return {key: value for key, value in approval.items() if key != "approval_digest"}


def command_apply(args):
    source = _targets([args.target])[0]
    state = _state(args.state_dir)
    ensure_outside(state, source)
    output = _path(args.output)
    ensure_outside(output, source)
    ensure_outside(output, state)
    proposal_path, approval_path = _path(args.proposal_file), _path(args.approval_file)
    ensure_outside(proposal_path, source)
    ensure_outside(proposal_path, state)
    ensure_outside(approval_path, source)
    ensure_outside(approval_path, state)
    proposal_data, approval_data = _read_json(args.proposal_file), _read_json(args.approval_file)
    validate_contract("proposal", proposal_data)
    validate_contract("approval", approval_data)
    # The same owned history must contain the latest exact approval decision.
    require_approved_decision(state, approval_data, source)
    result = apply(source, proposal_data, approval_data, output)
    postimage = inventory(output)
    result["static_verification"] = {
        "status": "completed",
        "source_digest": postimage.digest,
        "findings": analyze(postimage),
        "limitations": ["Static analysis completed; findings are unverified unless separately reproduced."],
    }
    record_decision(state, {
        "proposal_id": approval_data["proposal_id"], "base_digest": approval_data["base_digest"],
        "proposal_digest": approval_data["proposal_digest"], "decision": "apply",
        "reason": approval_data.get("reason", ""), "timestamp": approval_data["timestamp"],
        "output_digest": result["output_digest"],
    })
    proposal_path.unlink(missing_ok=True)
    approval_path.unlink(missing_ok=True)
    return result


def command_dismiss(args):
    report = _read_json(args.report)
    validate_contract("report", report)
    return dismiss(_state(args.state_dir), report, args.finding_id, args.reason)


def command_forget(args):
    return forget(_state(args.state_dir))


def command_profile(args):
    return _load_profile(args.profile)


def command_sandbox(args):
    source = _targets([args.target])[0]
    config = SandboxConfig(
        image=args.image, cpus=args.cpus, memory_mib=args.memory_mib, pids=args.pids,
        timeout=args.timeout, output_bytes=args.output_bytes,
    )
    return run_test(source, args.script, args.args, config)


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--state-dir")
    root = argparse.ArgumentParser(prog="refiner.py")
    commands = root.add_subparsers(dest="command", required=True)
    review_p = commands.add_parser("review", parents=[common])
    review_p.add_argument("target", nargs="+")
    review_p.add_argument("--profile")
    review_p.add_argument("--context", default="")
    review_p.add_argument("--force-refresh", action="store_true")
    review_p.add_argument("--report-file")
    review_p.set_defaults(handler=command_review)
    semantic_p = commands.add_parser("semantic", parents=[common])
    semantic_p.add_argument("target"); semantic_p.add_argument("--report", required=True); semantic_p.add_argument("--findings", required=True); semantic_p.add_argument("--report-file")
    semantic_p.set_defaults(handler=command_semantic)
    payload_p = commands.add_parser("payload")
    payload_p.add_argument("target"); payload_p.set_defaults(handler=command_payload)
    propose_p = commands.add_parser("propose", parents=[common])
    propose_p.add_argument("target"); propose_p.add_argument("--report", required=True); propose_p.add_argument("--changes", required=True); propose_p.add_argument("--purpose", required=True)
    propose_p.add_argument("--risk", default="Requires explicit approval"); propose_p.add_argument("--verification", action="append", default=[]); propose_p.add_argument("--proposal-file", required=True)
    propose_p.set_defaults(handler=command_propose)
    approve_p = commands.add_parser("approve", parents=[common])
    approve_p.add_argument("--target", required=True); approve_p.add_argument("--report", required=True); approve_p.add_argument("--proposal-file", required=True); approve_p.add_argument("--base-digest", required=True); approve_p.add_argument("--proposal-digest", required=True)
    approve_p.add_argument("--decision", choices=("apply", "reject"), required=True); approve_p.add_argument("--reason", default=""); approve_p.add_argument("--approval-file", required=True)
    approve_p.set_defaults(handler=command_approve)
    apply_p = commands.add_parser("apply", parents=[common])
    apply_p.add_argument("target"); apply_p.add_argument("--proposal-file", required=True); apply_p.add_argument("--approval-file", required=True); apply_p.add_argument("--output", required=True)
    apply_p.set_defaults(handler=command_apply)
    dismiss_p = commands.add_parser("dismiss", parents=[common])
    dismiss_p.add_argument("--report", required=True); dismiss_p.add_argument("--finding-id", required=True); dismiss_p.add_argument("--reason", required=True); dismiss_p.set_defaults(handler=command_dismiss)
    forget_p = commands.add_parser("forget", parents=[common]); forget_p.set_defaults(handler=command_forget)
    profile_p = commands.add_parser("profile"); profile_p.add_argument("--profile"); profile_p.set_defaults(handler=command_profile)
    sandbox_p = commands.add_parser("sandbox")
    sandbox_p.add_argument("target"); sandbox_p.add_argument("--script", required=True); sandbox_p.add_argument("--image", default=DEFAULT_IMAGE)
    sandbox_p.add_argument("--cpus", type=float, default=1); sandbox_p.add_argument("--memory-mib", type=int, default=512); sandbox_p.add_argument("--pids", type=int, default=64)
    sandbox_p.add_argument("--timeout", type=float, default=30); sandbox_p.add_argument("--output-bytes", type=int, default=1048576); sandbox_p.add_argument("--args", nargs=argparse.REMAINDER, default=[])
    sandbox_p.set_defaults(handler=command_sandbox)
    return root


def main(argv=None) -> int:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        args = parser().parse_args(argv)
        _emit(args.handler(args))
        return 0
    except (RefinerError, OSError, ValueError) as error:
        message = str(error)
        safe = {"Proposal is outdated for the current source"}
        sys.stderr.write((redact(message) if message in safe else "Request rejected") + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
