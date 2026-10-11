from __future__ import annotations

import ast
import re
from copy import deepcopy
from pathlib import PurePosixPath
from urllib.parse import unquote

from .common import RefinerError, digest, redact, redact_tree, secret_values
from .snapshot import textual_files

try:
    import yaml
    from yaml.tokens import AliasToken
except ImportError:  # pragma: no cover - packaging pins PyYAML
    yaml = None
    AliasToken = object


_ENUMS = {
    "category": {"security", "quality", "metadata", "link", "syntax", "compatibility"},
    "severity": {"info", "low", "medium", "high", "critical"},
    "verification": {"unverified", "verified"},
    "provenance": {"static", "semantic"},
}
_EXECUTION = re.compile(r"(?i)(?:\b(?:curl|wget|invoke-webrequest)\b[^\n|]*\|\s*(?:sh|bash|zsh|cmd|powershell)|\b(?:eval|exec|subprocess\.(?:run|call|popen)|os\.system)\s*\(|\bshell\s*=\s*true)")
_INJECTION = re.compile(r"(?i)(?:ignore (?:previous|all) instructions|system prompt|you are now|do not reveal|bypass (?:security|policy))")
_LINK = re.compile(r"!?\[[^\]\n]*\]\(\s*(?:<([^>\n]+)>|([^\s)\n]+))(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^()\n]*\)))?\s*\)")
_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_FENCE = re.compile(r"(?ms)^\s*(```|~~~).*?^\s*\1[^\n]*$")
_INLINE_CODE = re.compile(r"`+[^`\n]*`+")
_YAML_MAX_BYTES = 64 * 1024
_YAML_MAX_ALIASES = 0
_YAML_MAX_NODES = 2_048
_YAML_MAX_DEPTH = 40
_SEMANTIC_MAX = 128
_FINDING_FIELDS = {"id", "rule", "path", "path_digest", "evidence", "evidence_digest", "line", "category", "severity", "message", "verification", "provenance"}


class _BoundedFindings(list):
    """Stop explicitly rather than silently hiding excessive diagnostics."""
    def append(self, item):
        if len(self) >= 2000:
            raise RefinerError("Static finding limit exceeded; split the review scope")
        super().append(item)

    def extend(self, items):
        for item in items:
            self.append(item)


def _text(raw: bytes) -> str:
    return raw.decode("utf-8")


def _line(text: str, evidence: str) -> int:
    position = text.find(evidence)
    return text[:position].count("\n") + 1 if position >= 0 else 1


def make_finding(rule, path, evidence, line, category, severity, message, verification="unverified", provenance="static") -> dict:
    evidence = str(evidence)
    cleaned = " ".join(evidence.split())
    return {
        "id": digest({"rule": rule, "path": path, "evidence": cleaned}),
        "rule": rule,
        "path": path,
        "evidence": evidence,
        "evidence_digest": digest(evidence),
        "line": int(line),
        "category": category,
        "severity": severity,
        "message": str(message),
        "verification": verification,
        "provenance": provenance,
    }


if yaml is not None:
    class _UniqueSafeLoader(yaml.SafeLoader):
        pass

    def _unique_mapping(loader, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as error:
                raise yaml.constructor.ConstructorError("mapping", node.start_mark, "unhashable key", key_node.start_mark) from error
            if duplicate:
                raise yaml.constructor.ConstructorError("mapping", node.start_mark, f"duplicate key: {key}", key_node.start_mark)
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    _UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _bounded_yaml(header: str):
    if yaml is None:
        return None
    if len(header.encode("utf-8")) > _YAML_MAX_BYTES:
        raise ValueError("YAML header exceeds size limit")
    aliases = 0
    tokens = 0
    for token in yaml.scan(header, Loader=_UniqueSafeLoader):
        tokens += 1
        aliases += isinstance(token, AliasToken)
        if aliases > _YAML_MAX_ALIASES or tokens > _YAML_MAX_NODES * 8:
            raise ValueError("YAML header exceeds complexity limit")
    parsed = yaml.load(header, Loader=_UniqueSafeLoader)
    seen: set[int] = set()
    active: set[int] = set()
    count = 0

    def visit(value, depth=0):
        nonlocal count
        if depth > _YAML_MAX_DEPTH:
            raise ValueError("YAML header exceeds depth limit")
        if not isinstance(value, (dict, list)):
            count += 1
            if count > _YAML_MAX_NODES:
                raise ValueError("YAML header exceeds node limit")
            return
        identity = id(value)
        if identity in active:
            raise ValueError("Recursive YAML aliases are not accepted")
        if identity in seen:
            return
        seen.add(identity)
        active.add(identity)
        count += 1
        if count > _YAML_MAX_NODES:
            raise ValueError("YAML header exceeds node limit")
        children = [part for pair in value.items() for part in pair] if isinstance(value, dict) else value
        for child in children:
            visit(child, depth + 1)
        active.remove(identity)

    visit(parsed)
    return parsed


def _frontmatter(path: str, original: str) -> list[dict]:
    text = original.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if not text.startswith("---\n"):
        return [make_finding("frontmatter", path, text.split("\n", 1)[0], 1, "metadata", "medium", "SKILL.md requires YAML frontmatter")]
    end_match = re.search(r"(?m)^---\s*$", text[4:])
    if not end_match:
        return [make_finding("frontmatter", path, "---", 1, "metadata", "medium", "Frontmatter is not closed")]
    header = text[4:4 + end_match.start()]
    try:
        parsed = _bounded_yaml(header)
    except Exception:
        return [make_finding("frontmatter-yaml", path, header[:4096], 1, "syntax", "high", "Frontmatter is not valid bounded safe YAML")]
    findings: list[dict] = []
    if not isinstance(parsed, dict):
        findings.append(make_finding("frontmatter-schema", path, header[:4096], 1, "metadata", "high", "Frontmatter must be a mapping"))
        return findings
    name = parsed.get("name")
    if not isinstance(name, str) or not _NAME.fullmatch(name) or len(name) >= 64:
        findings.append(make_finding("frontmatter-name", path, str(name), 1, "metadata", "medium", "Frontmatter name must be lowercase kebab-case under 64 characters"))
    description = parsed.get("description")
    if not isinstance(description, str) or not description.strip():
        findings.append(make_finding("frontmatter-schema", path, "description", 1, "metadata", "medium", "Frontmatter requires a non-empty description"))
    return findings


def _openai_yaml(path: str, text: str) -> list[dict]:
    try:
        parsed = _bounded_yaml(text.removeprefix("\ufeff"))
    except Exception:
        return [make_finding("openai-yaml", path, text[:4096], 1, "syntax", "high", "agents/openai.yaml is not valid bounded safe YAML")]
    if not isinstance(parsed, dict):
        return [make_finding("openai-schema", path, text[:4096], 1, "metadata", "high", "agents/openai.yaml must be a mapping")]
    findings: list[dict] = []
    allowed = {"display_name", "description", "default_prompt", "interface", "dependencies", "policy"}
    unknown = set(parsed) - allowed
    if unknown:
        findings.append(make_finding("openai-schema", path, ", ".join(sorted(map(str, unknown))), 1, "metadata", "medium", "agents/openai.yaml contains unsupported fields"))
    command_keys = {"command", "commands", "exec", "execute", "shell", "script", "scripts", "hook", "hooks"}

    def command_scan(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).casefold() in command_keys:
                    findings.append(make_finding("openai-command", path, str(key), 1, "security", "high", "Executable commands are not accepted from agents/openai.yaml"))
                command_scan(child)
        elif isinstance(value, list):
            for child in value:
                command_scan(child)

    command_scan(parsed)
    interface = parsed.get("interface")
    if interface is not None:
        interface_fields = {"display_name", "short_description", "description", "icon_small", "icon_large", "brand_color", "default_prompt"}
        if not isinstance(interface, dict) or set(interface) - interface_fields or any(not isinstance(v, str) or not v.strip() for v in interface.values()):
            findings.append(make_finding("openai-interface", path, "interface", 1, "metadata", "medium", "agents/openai.yaml interface is invalid"))
    else:
        for key in ("display_name", "description", "default_prompt"):
            if not isinstance(parsed.get(key), str) or not parsed[key].strip():
                findings.append(make_finding("openai-interface", path, key, 1, "metadata", "medium", f"agents/openai.yaml requires {key}"))
    dependencies = parsed.get("dependencies")
    if dependencies is not None:
        valid = isinstance(dependencies, dict) and set(dependencies) <= {"tools"} and isinstance(dependencies.get("tools", []), list)
        if not valid:
            findings.append(make_finding("openai-dependencies", path, "dependencies", 1, "metadata", "medium", "agents/openai.yaml dependencies policy is invalid"))
    policy = parsed.get("policy")
    if policy is not None and (not isinstance(policy, dict) or set(policy) - {"allow_implicit_invocation"} or not isinstance(policy.get("allow_implicit_invocation"), bool)):
        findings.append(make_finding("openai-policy", path, "policy", 1, "metadata", "medium", "agents/openai.yaml policy is invalid"))
    return findings


def _without_code(text: str) -> str:
    def blank(match):
        return "".join("\n" if char == "\n" else " " for char in match.group(0))
    return _INLINE_CODE.sub(blank, _FENCE.sub(blank, text))


def _normalise_link(source_path: str, target: str) -> tuple[str | None, str | None]:
    target = unquote(target).replace("\\", "/")
    if not target or target.startswith("#") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
        return None, None
    target = target.split("#", 1)[0].split("?", 1)[0]
    if target.startswith(("/", "//")) or re.match(r"^[A-Za-z]:", target):
        return None, "unsafe"
    parts = list(PurePosixPath(source_path).parent.parts)
    for part in target.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                return None, "unsafe"
            parts.pop()
        else:
            parts.append(part)
    if not parts:
        return None, "unsafe"
    return "/".join(parts), None


def analyze(snapshot) -> list[dict]:
    findings: list[dict] = _BoundedFindings()
    files = textual_files(snapshot)
    known = set(snapshot.files)
    if "SKILL.md" not in snapshot.files:
        findings.append(make_finding("skill-structure", "SKILL.md", "SKILL.md", 1, "metadata", "high", "Skill root requires a regular textual SKILL.md"))
    elif "SKILL.md" not in files:
        findings.append(make_finding("skill-structure", "SKILL.md", "SKILL.md", 1, "metadata", "high", "SKILL.md must be UTF-8 text within the analysis size limit"))
    for path in sorted(snapshot.files):
        for value in secret_values(path):
            findings.append(make_finding("embedded-secret", path, value, 1, "security", "high", "Secret-like material in a filename requires rotation"))
    for path, text in sorted(files.items()):
        if path == "SKILL.md":
            findings.extend(_frontmatter(path, text))
        if path == "agents/openai.yaml":
            findings.extend(_openai_yaml(path, text))
        if path.endswith(".py"):
            try:
                ast.parse(text, filename=path)
            except SyntaxError as error:
                findings.append(make_finding("python-syntax", path, error.text or "", error.lineno or 1, "syntax", "high", "Python does not parse"))
        for match in _EXECUTION.finditer(text):
            findings.append(make_finding("unsafe-execution", path, match.group(0), _line(text, match.group(0)), "security", "high", "Potential command execution requires human review"))
        for match in _INJECTION.finditer(text):
            findings.append(make_finding("prompt-injection", path, match.group(0), _line(text, match.group(0)), "security", "high", "Suspicious instruction pattern requires review"))
        for value in secret_values(text):
            findings.append(make_finding("embedded-secret", path, value, _line(text, value), "security", "high", "Embedded secret requires rotation"))
        if path.lower().endswith(".md"):
            visible = _without_code(text)
            for match in _LINK.finditer(visible):
                target = match.group(1) or match.group(2)
                resolved, problem = _normalise_link(path, target)
                if problem:
                    findings.append(make_finding("unsafe-local-link", path, target, _line(visible, match.group(0)), "link", "high", "Local link escapes the skill or uses an absolute path"))
                elif resolved is not None and resolved not in known:
                    findings.append(make_finding("broken-local-link", path, target, _line(visible, match.group(0)), "link", "medium", "Local link does not exist"))
    return _redact_findings(findings, _secrets(snapshot))


def _secrets(snapshot) -> list[str]:
    values: list[str] = []
    for path, raw in snapshot.files.items():
        values.extend(secret_values(path))
        values.extend(secret_values(raw.decode("utf-8", errors="ignore")))
    return values


def _redact_findings(findings, secrets):
    return [redact_tree(item, secrets) for item in findings]


def semantic_payload(snapshot) -> dict:
    secrets = _secrets(snapshot)
    payload = {
        "trust": "UNTRUSTED",
        "source_digest": snapshot.digest,
        "manifest": [{**item, "path_digest": digest(item["path"])} for item in snapshot.manifest],
        "omitted": [{**item, "path_digest": digest(item["path"])} for item in snapshot.omitted],
        "files": [
            {"path": path, "path_digest": digest(path), "content": content}
            for path, content in sorted(textual_files(snapshot).items())
        ],
    }
    return redact_tree(payload, secrets)


def _validated_semantic(candidate: dict, raw: dict[str, str], secrets: list[str]) -> dict:
    if not isinstance(candidate, dict) or set(candidate) - _FINDING_FIELDS:
        raise RefinerError("Invalid semantic finding field")
    required = {"rule", "evidence", "category", "severity", "message"}
    if not required <= set(candidate):
        raise RefinerError("Semantic finding is missing a required field")
    item = dict(candidate)
    if "id" in item and not isinstance(item["id"], str):
        raise RefinerError("Semantic finding id is invalid")
    if "evidence_digest" in item and not isinstance(item["evidence_digest"], str):
        raise RefinerError("Semantic finding evidence digest is invalid")
    if "line" in item and (not isinstance(item["line"], int) or isinstance(item["line"], bool)):
        raise RefinerError("Semantic finding line is invalid")
    if "verification" in item and item["verification"] not in _ENUMS["verification"]:
        raise RefinerError("Invalid finding verification")
    if "provenance" in item and item["provenance"] not in _ENUMS["provenance"]:
        raise RefinerError("Invalid finding provenance")
    for field in ("rule", "evidence", "message"):
        if not isinstance(item[field], str):
            raise RefinerError("Semantic finding text field is invalid")
    if not item["rule"] or len(item["rule"]) > 128 or not item["message"] or len(item["message"]) > 4096 or not item["evidence"] or len(item["evidence"]) > 4096:
        raise RefinerError("Semantic finding exceeds field limits")
    for field in ("category", "severity"):
        if item.get(field) not in _ENUMS[field]:
            raise RefinerError(f"Invalid finding {field}")
    path = item.get("path")
    path_digest = item.get("path_digest")
    if path_digest is not None and (not isinstance(path_digest, str) or path_digest not in {digest(value) for value in raw}):
        raise RefinerError("Finding path digest is invalid")
    if path_digest is not None:
        resolved = next(value for value in raw if digest(value) == path_digest)
        if path is not None and path not in {resolved, redact(resolved, secrets)}:
            raise RefinerError("Finding path does not match path digest")
        path = resolved
    if not isinstance(path, str):
        raise RefinerError("Finding path is required")
    if path not in raw:
        raise RefinerError("Finding evidence references an unknown or omitted file")
    evidence = item["evidence"]
    source = raw[path]
    display_source = redact(source, secrets)
    identity_evidence = evidence
    if evidence in source:
        canonical_line = _line(source, evidence)
    elif evidence in display_source:
        canonical_line = _line(display_source, evidence)
        raw_line = source.splitlines()[canonical_line - 1] if canonical_line <= len(source.splitlines()) else ""
        display_line = redact(raw_line, secrets)
        if display_line == evidence:
            identity_evidence = raw_line
    else:
        raise RefinerError("Finding evidence is not concrete")
    built = make_finding(item["rule"], path, identity_evidence, canonical_line, item["category"], item["severity"], item["message"], verification="unverified", provenance="semantic")
    built["path_digest"] = digest(path)
    built["evidence"] = evidence
    return redact_tree(built, secrets)


def merge_semantic(snapshot, report, findings) -> dict:
    if not isinstance(findings, list) or len(findings) > _SEMANTIC_MAX:
        raise RefinerError("Invalid semantic findings")
    if not isinstance(report, dict) or not isinstance(report.get("findings"), list):
        raise RefinerError("Invalid review report")
    secrets = _secrets(snapshot)
    raw = textual_files(snapshot)
    merged = deepcopy(report)
    accepted: list[dict] = []
    seen = {item.get("id") for item in report["findings"] if isinstance(item, dict)}
    for candidate in findings:
        item = _validated_semantic(candidate, raw, secrets)
        if item["id"] not in seen:
            accepted.append(item)
            seen.add(item["id"])
    merged["findings"] = list(report["findings"]) + accepted
    return redact_tree(merged, secrets)
