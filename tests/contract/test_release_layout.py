from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ReleaseLayoutTests(unittest.TestCase):
    def test_layout_is_positive_and_complete(self) -> None:
        layout = json.loads((ROOT / "tools" / "release_layout.json").read_text(encoding="utf-8"))
        self.assertEqual(layout["schema_version"], 1)
        self.assertEqual(set(layout["skills"]), {"houdini-bridge", "nuke-bridge", "vfx-visual-twin"})
        for skill_name, config in layout["skills"].items():
            skill_root = ROOT / "skills" / skill_name
            self.assertTrue(skill_root.is_dir())
            self.assertIn("SKILL.md", config["files"])
            self.assertEqual(len(config["files"]), len(set(config["files"])))
            for relative in config["files"]:
                self.assertNotIn("..", Path(relative).parts)
                self.assertTrue((skill_root / relative).is_file(), f"missing {skill_name}/{relative}")
            for package in config["runtime_packages"]:
                self.assertTrue((ROOT / "packages" / package / "pyproject.toml").is_file(), f"missing package {package}")
            for plugin in config["plugins"]:
                self.assertTrue((ROOT / "plugins" / plugin).is_dir(), f"missing plugin {plugin}")

    def test_each_skill_carries_formal_generator_and_default_worker_closure(self) -> None:
        layout = json.loads((ROOT/'tools/release_layout.json').read_text(encoding="utf-8"))
        native_resources = {'docs/native-basis/hda-interface-capture.json',
                            'docs/native-basis/native-boundary-metadata-supplement.json',
                            'docs/native-basis/hda-interface-22.0.459.json',
                            'docs/native-basis/supporting-sources-22.0.459.json'}
        capture = json.loads((ROOT/'docs/native-basis/hda-interface-22.0.459.json').read_text())
        originals = {'docs/native-basis/h22-459-originals/' + record['raw_section']
                     for record in capture['operators'].values() if record.get('status')=='CAPTURED_STATIC_DIALOG'}
        self.assertEqual(len(originals), 55)
        card_root = ROOT/'docs/real-acceptance-cards'
        cards = {path.relative_to(ROOT).as_posix() for path in card_root.iterdir() if path.is_file()}
        self.assertEqual(len(cards), 17)
        self.assertIn('docs/real-acceptance-cards/README.md', cards)
        expected_resources = native_resources | originals | cards
        for name, config in layout['skills'].items():
            self.assertEqual(config['deployment_trees'],['packages','plugins','tools','controller-entry'])
            self.assertEqual(set(config['deployment_resources']),expected_resources)
            for relative in config['deployment_trees']+config['deployment_resources']:
                self.assertFalse(Path(relative).is_absolute())
                self.assertNotIn('..',Path(relative).parts)
                self.assertTrue((ROOT/relative).exists())
            for relative in native_resources:
                self.assertIs(json.loads((ROOT/relative).read_text(encoding="utf-8"))['native_execution'],False)

    def test_visual_twin_release_contains_every_domain_reference(self) -> None:
        layout = json.loads((ROOT / "tools" / "release_layout.json").read_text(encoding="utf-8"))
        files = set(layout["skills"]["vfx-visual-twin"]["files"])
        domain_files = set((ROOT / "skills" / "vfx-visual-twin" / "references" / "domains").glob("*.md"))
        expected = {path.relative_to(ROOT / "skills" / "vfx-visual-twin").as_posix() for path in domain_files}
        self.assertEqual({item for item in files if item.startswith("references/domains/")}, expected)

    def test_layout_never_lists_macos_metadata(self) -> None:
        layout_text = (ROOT / "tools" / "release_layout.json").read_text(encoding="utf-8")
        self.assertNotIn(".DS_Store", layout_text)


if __name__ == "__main__":
    unittest.main()
