"""Repository-only structural validation; semantic mirror review remains separate."""
from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/skill-refiner/skills/skill-refiner"
sys.path.insert(0, str(SKILL / "scripts"))

from refinerlib.analysis import analyze
from refinerlib.contracts import validate_contract
from refinerlib.snapshot import inventory


def validate_package(root=ROOT):
    root = Path(root)
    marketplace = json.loads((root / ".agents/plugins/marketplace.json").read_text(encoding="utf-8"))
    assert marketplace["name"] == "skill-refiner-marketplace"
    assert len(marketplace["plugins"]) == 1
    entry = marketplace["plugins"][0]
    assert entry["source"] == {"source": "local", "path": "./plugins/skill-refiner"}
    plugin = root / entry["source"]["path"]
    manifest = json.loads((plugin / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == entry["name"] == "skill-refiner"
    assert manifest["version"] == "0.1.0"
    assert manifest["license"] == "MIT"
    assert manifest["author"]["name"] == "AdriAir"
    assert (plugin / "LICENSE").read_bytes() == (root / "LICENSE").read_bytes()
    assert (plugin / "LICENSE.es.md").read_bytes() == (root / "LICENSE.es.md").read_bytes()
    assert manifest["$schema"] == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    assert not any((plugin / name).exists() for name in (".codex-plugin", "mcp.json", ".mcp.json", "hooks"))
    assert sorted(p.relative_to(plugin).as_posix() for p in plugin.rglob("SKILL.md")) == ["skills/skill-refiner/SKILL.md"]
    skill = plugin / "skills/skill-refiner"
    findings = analyze(inventory(skill))
    blocking = [f for f in findings if f["category"] in {"metadata", "link", "syntax"}]
    assert not blocking, [(f["rule"], f["path"], f["evidence"]) for f in blocking]
    assert (skill / "scripts/refiner.py").is_file()
    assert (skill / "agents/openai.yaml").is_file()
    profile = json.loads((skill / "assets/profile.default.json").read_text(encoding="utf-8"))
    validate_contract("profile", profile)
    mirrors = json.loads((root / "docs/mirrors.json").read_text(encoding="utf-8"))["pairs"]
    listed = set()
    for pair in mirrors:
        english, spanish = (root / pair[key] for key in ("english", "spanish"))
        assert english.is_file() and spanish.is_file()
        contents = [p.read_text(encoding="utf-8") for p in (english, spanish)]
        sections = [re.findall(r"<!-- section: ([a-z0-9-]+) -->", text) for text in contents]
        assert sections[0] and sections[0] == sections[1] and len(set(sections[0])) == len(sections[0])
        assert all(len(text.strip()) > 100 for text in contents)
        listed.update((pair["english"], pair["spanish"]))
    documents = {p.relative_to(root).as_posix() for p in root.rglob("*.md") if not any(part in {".work", ".venv", ".git", ".pytest_cache", "fixtures"} for part in p.relative_to(root).parts)}
    assert documents <= listed, documents - listed
    return {"status": "passed", "discoverable_skills": 1, "mirror_pairs": len(mirrors), "semantic_equivalence": "requires-independent-review"}


if __name__ == "__main__":
    print(json.dumps(validate_package(), indent=2))
