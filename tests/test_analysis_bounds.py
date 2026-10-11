import pytest

from refinerlib.analysis import analyze
from refinerlib.common import RefinerError
from refinerlib.snapshot import inventory


def test_pattern_flood_fails_explicitly_before_building_unbounded_reports(tmp_path):
    (tmp_path / "SKILL.md").write_text("---\nname: demo\ndescription: Demo\n---\n")
    (tmp_path / "flood.py").write_text("eval('x')\n" * 2100)
    with pytest.raises(RefinerError, match="finding limit"):
        analyze(inventory(tmp_path))
