import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/skill-refiner/skills/skill-refiner/scripts"
sys.path.insert(0, str(SCRIPTS))
