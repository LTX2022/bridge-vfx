from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"\]\(([^)]+)\)")


class SkillResourceTests(unittest.TestCase):
    def test_skill_links_are_local_and_resolve(self) -> None:
        for skill_root in sorted((ROOT / "skills").iterdir()):
            entry = skill_root / "SKILL.md"
            if not entry.is_file():
                continue
            text = entry.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"))
            self.assertIn(f"name: {skill_root.name}\n", text)
            for target in LINK.findall(text):
                if "://" in target or target.startswith("#"):
                    continue
                clean = target.split("#", 1)[0]
                self.assertTrue((skill_root / clean).is_file(), f"broken link in {entry}: {target}")

    def test_visual_twin_entrypoint_stays_progressive(self) -> None:
        path = ROOT / "skills" / "vfx-visual-twin" / "SKILL.md"
        text = path.read_text(encoding="utf-8")
        self.assertLess(len(text.splitlines()), 80)
        self.assertIn("references/domains/INDEX.md", text)
        self.assertNotIn("voxel_size", text)
        self.assertNotIn("particle separation", text.lower())


if __name__ == "__main__":
    unittest.main()
