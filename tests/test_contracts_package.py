import importlib.util
from pathlib import Path

import pytest
from refinerlib.common import RefinerError
from refinerlib.contracts import validate_contract
from refinerlib.history import review, complete_review
from refinerlib.proposals import propose, approve


def test_actual_runtime_artifacts_match_packaged_contracts(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "SKILL.md").write_text("---\nname: example\ndescription: Example\n---\n[Missing](absent.md)\n")
    report = review(source, tmp_path / "state")
    validate_contract("report", report)
    for finding in report["findings"]:
        validate_contract("finding", finding)
    completed = complete_review(source, report, tmp_path / "state", [])
    validate_contract("report", completed)
    proposal = propose(source, [{"path":"SKILL.md", "old":"[Missing](absent.md)", "new":"Example"}], "Remove broken link")
    validate_contract("proposal", proposal)
    validate_contract("approval", approve(proposal, proposal["base_digest"], proposal["proposal_digest"], "apply"))


def test_schema_rejects_unknown_profile_controls_without_value_in_error():
    with pytest.raises(RefinerError, match="Invalid profile contract") as error:
        validate_contract("profile", {"disable_security":"syntheticprivatecredential123"})
    assert "syntheticprivatecredential123" not in str(error.value)


def test_package_discovery_references_and_bilingual_structure():
    path = Path(__file__).resolve().parents[1] / "scripts/validate_package.py"
    spec = importlib.util.spec_from_file_location("package_validation", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.validate_package()["discoverable_skills"] == 1


def test_public_package_identity_uses_skill_refiner_paths_and_mit_license():
    root = Path(__file__).resolve().parents[1]
    marketplace = (root / ".agents/plugins/marketplace.json").read_text(encoding="utf-8")
    manifest = (root / "plugins/skill-refiner/plugin.json").read_text(encoding="utf-8")
    assert '"name": "skill-refiner-marketplace"' in marketplace
    assert '"path": "./plugins/skill-refiner"' in marketplace
    assert '"name": "skill-refiner"' in manifest
    assert '"license": "MIT"' in manifest
    assert '"name": "AdriAir"' in manifest
    assert (root / "plugins/skill-refiner/LICENSE").read_bytes() == (root / "LICENSE").read_bytes()
    assert (root / "plugins/skill-refiner/skills/skill-refiner/SKILL.md").is_file()
