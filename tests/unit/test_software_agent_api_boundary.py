from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "packages/houdini-bridge/src"))

from software_agent_api_boundary import AgentAPIError, FORMAT, ORIGIN, install_agent_api
from houdini_bridge import crowd_helpers as helpers


def fixture(version="21.0.631", rate=30.7, start=12.5):
    hou = SimpleNamespace(
        applicationVersionString=lambda: version,
        attribType=SimpleNamespace(Global="detail", Point="point", Prim="primitive", Vertex="vertex"),
        _software_agent_api_state={"origin": ORIGIN, "clip_sample_rate": rate, "clip_start_time": start})
    install_agent_api(hou)
    return hou


class SoftwareAgentAPITests(unittest.TestCase):
    def test_production_builder_and_snapshot_survive_new_api_instance(self):
        self.assertEqual(Path(helpers.__file__).resolve(), ROOT / "packages/houdini-bridge/src/houdini_bridge/crowd_helpers.py")
        for version in helpers.SUPPORTED_VERSIONS:
            with self.subTest(version=version):
                hou = fixture(version)
                geometry, before, handoff = helpers.build_synthetic_agent_geometry(hou)
                self.assertIsInstance(geometry.prims()[0], hou.Agent)
                self.assertEqual((handoff["sample_rate"], handoff["start_time"]), (30.7, 12.5))
                self.assertAlmostEqual(handoff["length_seconds"], 2 / 30.7)
                wire = geometry.data()
                self.assertEqual(json.loads(wire)["format"], FORMAT)
                other = fixture(version, rate=17.0, start=-6.0)
                reopened = other.Geometry()
                reopened.loadFromString(wire)
                after = helpers.snapshot_agent_geometry(other, reopened)
                self.assertEqual(before, after)
                self.assertEqual(wire, reopened.data())
                self.assertTrue(helpers.compare_agent_snapshots(before, after)["content_equivalent"])
                self.assertEqual(handoff, helpers.validate_synthetic_snapshot(after))
                self.assertIs(reopened.prims()[0].clips()[0], reopened.prims()[0].definition().clips()[0])
                self.assertIs(reopened.prims()[0].currentLayers()[0], reopened.prims()[0].definition().layers()[0])

    def test_mutated_rig_shape_clip_and_pose_are_read_and_persisted(self):
        def rig(hou, agent):
            agent.definition().rig().setRestLocalTransforms([hou.Matrix4(1), hou.hmath.buildTranslate(0, 1, 0)])

        def shape(hou, agent):
            agent.definition().shapeLibrary().shapes()[0].geometry().prims()[0].setIsClosed(False)

        def clip(hou, agent):
            agent.definition().clips()[0].setLocalTransforms(2, [hou.Matrix4(1), hou.hmath.buildTranslate(9, 8, 7)])

        def pose(hou, agent):
            agent.setLocalTransform(hou.hmath.buildTranslate(2, 3, 4), 1)

        def binding(hou, agent):
            agent.setCurrentLayers([])

        for label, mutate in (("rig", rig), ("shape", shape), ("clip", clip), ("pose", pose), ("binding", binding)):
            with self.subTest(component=label):
                hou = fixture()
                geometry, before, _ = helpers.build_synthetic_agent_geometry(hou)
                mutate(hou, geometry.prims()[0])
                changed = helpers.snapshot_agent_geometry(hou, geometry)
                with self.assertRaises(helpers.CrowdDataError):
                    helpers.validate_synthetic_snapshot(changed)
                with self.assertRaises(helpers.CrowdDataError):
                    helpers.compare_agent_snapshots(before, changed)
                other = fixture()
                reopened = other.Geometry(); reopened.loadFromString(geometry.data())
                after = helpers.snapshot_agent_geometry(other, reopened)
                self.assertEqual(changed, after)
                self.assertTrue(helpers.compare_agent_snapshots(changed, after)["content_equivalent"])

    def test_ordinary_points_polygon_and_all_attribute_scopes_roundtrip(self):
        hou = fixture(); geo = hou.Geometry()
        detail = geo.addAttrib(hou.attribType.Global, "label", "")
        point = geo.addAttrib(hou.attribType.Point, "id", 0)
        prim = geo.addAttrib(hou.attribType.Prim, "mass", 0.0)
        vertex = geo.addAttrib(hou.attribType.Vertex, "uv", (0.0, 0.0))
        geo.setGlobalAttribValue(detail, "kept")
        polygon = geo.createPolygon(False)
        for i, position in enumerate(((1, 2, 3, 0.5), (4, 5, 6), (7, 8, 9))):
            p = geo.createPoint(); p.setPosition(position); p.setAttribValue(point, i + 7)
            v = polygon.addVertex(p); v.setAttribValue(vertex, (i / 10.0, i / 20.0))
        polygon.setAttribValue(prim, 1.25)
        duplicate = hou.Geometry(geo, clone_data_ids=True)
        self.assertEqual(geo.data(), duplicate.data())
        duplicate.points()[0].setPosition((10, 11, 12))
        self.assertEqual(geo.points()[0].position(), (1.0, 2.0, 3.0))
        other = fixture(); loaded = other.Geometry(); loaded.loadFromString(duplicate.data())
        self.assertEqual(duplicate.data(), loaded.data())
        self.assertFalse(loaded.prims()[0].isClosed())
        self.assertEqual(loaded.attribValue("label"), "kept")
        self.assertEqual([p.attribValue("id") for p in loaded.points()], [7, 8, 9])
        self.assertEqual(loaded.prims()[0].attribValue("mass"), 1.25)
        self.assertEqual(loaded.prims()[0].vertices()[2].attribValue("uv"), (0.2, 0.1))
        self.assertEqual(json.loads(loaded.data())["geometry"]["points"][0]["weight"], 0.5)
        loaded.points()[0].setAttribValue("P", (2.0, 4.0, 6.0))
        self.assertEqual(loaded.points()[0].position(), (2.0, 4.0, 6.0))

    def test_constructor_and_finite_interface_fail_closed(self):
        hou = fixture(); rig = hou.AgentRig("r", ["root"], [[]]); library = hou.AgentShapeLibrary()
        for label, call, error in (
            ("hierarchy", lambda: hou.AgentRig("r", ["r"], [[0]]), AgentAPIError),
            ("clip_count", lambda: hou.AgentClip("c", rig, 3.0), AgentAPIError),
            ("clip_fps_keyword", lambda: hou.AgentClip("c", rig, 3, sample_rate=24), TypeError),
            ("clip_file_overload", lambda: hou.AgentClip("c", "file", rig), AgentAPIError),
            ("layer_binding", lambda: hou.AgentLayer("l", rig, library, [None]), AgentAPIError),
            ("geometry_unknown_kw", lambda: hou.Geometry(fps=24), TypeError),
            ("packed_kind", lambda: hou.Geometry().createPacked("PackedDisk"), AgentAPIError),
            ("point_ownership", lambda: hou.Geometry().createPacked("PackedAgent", hou.Geometry().createPoint()), AgentAPIError),
            ("unknown_method", lambda: hou.Geometry().cook(), AttributeError),
            ("matrix_size", lambda: hou.Matrix4([1, 2]), AgentAPIError)):
            with self.subTest(contract=label), self.assertRaises(error): call()
        for state in ({}, {"origin": "runtime_hom", "clip_sample_rate": 24, "clip_start_time": 0},
                      {"origin": ORIGIN, "clip_sample_rate": 0, "clip_start_time": 0}):
            with self.subTest(state=state), self.assertRaises(AgentAPIError):
                install_agent_api(SimpleNamespace(_software_agent_api_state=state, applicationVersionString=lambda: "21.0.631"))
        definition = hou.AgentDefinition(rig, library)
        with self.assertRaises(AgentAPIError):
            definition.addClip(hou.AgentClip("c", hou.AgentRig("other", ["root"], [[]]), 3))

    def test_malformed_state_is_rejected_without_partial_replacement(self):
        hou = fixture(); geo, _, _ = helpers.build_synthetic_agent_geometry(hou)
        before = geo.data(); valid = json.loads(before)
        def missing_rig(data): del data["geometry"]["primitives"][0]["agent"]["definition"]["rig"]["rest_local"]
        def missing_shape(data): data["geometry"]["primitives"][0]["agent"]["definition"]["library"]["shapes"] = []
        def malformed_sample(data): data["geometry"]["primitives"][0]["agent"]["definition"]["clips"][0]["samples"][0] = []
        def missing_pose(data): data["geometry"]["primitives"][0]["agent"]["pose_local"] = []
        def scalar_matrix(data): data["geometry"]["primitives"][0]["agent"]["pose_local"][0] = 1
        def unknown_prim(data): data["geometry"]["primitives"][0]["kind"] = "Unknown"
        def wrong_timing(data): data["geometry"]["primitives"][0]["agent"]["definition"]["clips"][0]["sample_rate"] = 0
        def bad_vertex(data): data["geometry"]["primitives"][0]["vertices"][0]["point"] = 99
        for label, mutate in (("rig", missing_rig), ("shape", missing_shape), ("clip", malformed_sample),
                              ("pose", missing_pose), ("scalar_matrix", scalar_matrix), ("kind", unknown_prim),
                              ("timing", wrong_timing), ("vertex", bad_vertex)):
            data = copy.deepcopy(valid); mutate(data)
            with self.subTest(component=label), self.assertRaises(AgentAPIError):
                geo.loadFromString(json.dumps(data).encode())
            self.assertEqual(before, geo.data())
        for malformed in (b"", b"{}", b"not JSON", b'{"format":1,"format":2}', before.decode()):
            with self.subTest(wire=repr(malformed)[:40]), self.assertRaises(AgentAPIError):
                geo.loadFromString(malformed)
            self.assertEqual(before, geo.data())
        incomplete = hou.Geometry(); incomplete.createPacked("PackedAgent")
        with self.assertRaises(AgentAPIError): helpers.snapshot_agent_geometry(hou, incomplete)

    def test_world_transforms_follow_row_major_hierarchy_and_point_translation(self):
        hou = fixture(); rig = hou.AgentRig("r", ["root", "child"], [[1], []])
        rotate_translate = hou.Matrix4((0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1, 0, 10, 20, 30, 1))
        child = hou.hmath.buildTranslate((2, 3, 4))
        rig.setRestLocalTransforms([rotate_translate, child])
        self.assertEqual(rig.restWorldTransform(1).asTuple()[12:15], (7.0, 22.0, 34.0))
        clip = hou.AgentClip("c", rig, 3); clip.setLocalTransforms(1, [rotate_translate, child])
        self.assertEqual(clip.worldTransforms(1)[1].asTuple(), rig.restWorldTransform(1).asTuple())
        agent_geo = hou.Geometry(); agent = agent_geo.createPacked("PackedAgent")
        agent.setDefinition(hou.AgentDefinition(rig, hou.AgentShapeLibrary()))
        agent.setLocalTransform(rotate_translate, 0); agent.setLocalTransform(child, 1)
        agent_geo.points()[0].setPosition((8, 9, 10))
        self.assertEqual(agent.worldTransform(1).asTuple()[12:15], (7.0, 22.0, 34.0))
        self.assertEqual(agent.fullTransform().asTuple()[12:15], (8.0, 9.0, 10.0))
        self.assertEqual(hou.Matrix4().asTuple(), (0.0,) * 16)


if __name__ == "__main__":
    unittest.main()
