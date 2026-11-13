"""Exact-time output preflight through the shipped addon and explicit USD APIs."""
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from houdini_bridge import native_render_domains as native
from vfx_pipeline.workbuddy_assembly import software_host_client
import test_native_render_domains as existing

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "driver:parameters:husk:OpenEXR:"
api_spec = importlib.util.spec_from_file_location(
    "render_configuration_time_api", ROOT / "tools/software_render_api_boundary.py")
api = importlib.util.module_from_spec(api_spec)
api_spec.loader.exec_module(api)


class SampledAttribute(api.Attribute):
    """Bottom USD Attribute with separate default and authored time samples."""

    def __init__(self, kind, default, name, samples, *, error=None, drift=False):
        super().__init__(kind, default, name)
        self.samples = samples
        self.error = error
        self.drift = drift
        self.calls = []

    def Get(self, frame=None):
        self.calls.append(frame)
        if self.error is not None:
            raise self.error
        value = self.value if frame is None else self.samples[float(frame)]
        if self.drift and self.calls.count(frame) > 1:
            return "unsupported-after-repeated-read"
        return value


@contextmanager
def built_scene(version, domain, *, task_owned=False):
    with tempfile.TemporaryDirectory() as temporary, patch.dict(sys.modules), patch.dict(
        os.environ, {
            "BRIDGE_SKILLS_STATE_ROOT": temporary + "/state",
            "HOUDINI_BRIDGE_STATE_DIR": temporary + "/houdini",
            "BRIDGE_SKILLS_SCHEDULER_ROOT": temporary + "/scheduler",
        }
    ):
        client, addon = software_host_client(
            ROOT / "plugins/houdini/_impl/houdini_bridge_addon.py",
            Path(temporary) / "host")
        if task_owned:
            addon._TASK_HOST_IDENTITY = {**addon._host_identity(),
                'task_id': 'render-configuration-time', 'pid': os.getpid(),
                'launch_nonce': 'explicit-thread-process-boundary',
                'plugin_build': addon._FX_LOADED_ADDON_SHA256}
        interfaces, states, ports = api.interface_profiles(ROOT, version)
        existing.boundary.constrain_hou(
            ROOT / "docs/native-basis/hda-interface-capture.json", version,
            instance_states=states, native_api_interfaces=interfaces,
            native_api_ports=ports)
        hou = sys.modules["hou"]
        api.install_stage_api(hou)
        params = {
            "task_id": "render-configuration-time",
            "constraints": {"fx": {
                "domain_pack": domain, "run_mode": "diagnose", "frames": [1, 2]}},
            "render": {"frame_range": {"start": 1, "end": 2, "step": 1}},
        }
        built = client.call("agent.fx.build_preview", params)
        if built["execution_state"] != "EDITABLE_DOMAIN_GRAPH":
            raise AssertionError(built["execution_state"])
        roles = built["scene_manifest"]["nodes"]
        driver = hou.node(roles["render"])
        terminal = hou.node(roles["settings_binding"])
        original_stage = type(terminal).stage
        settings_path = driver.parm("rendersettings").eval()

        def configuration(attributes, frames):
            def sampled_stage(node, *arguments, **keywords):
                stage = original_stage(node, *arguments, **keywords)
                if node is terminal:
                    settings = stage.GetPrimAtPath(settings_path)
                    product_path = settings.GetRelationship("products").GetTargets()[0]
                    product = stage.GetPrimAtPath(product_path)
                    product.attributes.update({(key if key == "productName" else PREFIX + key): value
                                               for key, value in attributes.items()})
                return stage

            with patch.object(type(terminal), "stage", sampled_stage):
                return addon._fx_render_configuration(driver, frames)

        yield addon, configuration


class RenderConfigurationTimeTests(unittest.TestCase):
    def test_forwarded_render_relationships_resolve_to_actual_prims(self):
        for version in native.SUPPORTED_VERSIONS:
            with self.subTest(version=version), built_scene(version, native.LIGHTING) as (addon, configuration):
                driver = dict(zip(configuration.__code__.co_freevars,
                                  (cell.cell_contents for cell in configuration.__closure__)))['driver']
                original = api.Prim.GetRelationship

                def relation(prim, name):
                    actual = original(prim, name)
                    if name in {"products", "orderedVars", "camera"} and actual:
                        forwarded = actual.GetTargets()
                        actual.GetTargets = lambda: ["/Links." + name]
                        actual.GetForwardedTargets = lambda: forwarded
                    return actual

                with patch.object(api.Prim, 'GetRelationship', relation):
                    observed = addon._fx_render_configuration(driver, [1])["1"]
                self.assertEqual(observed['products'], observed['color_configuration_fact']['settings']['products']['forwarded_targets'])
                self.assertEqual(observed['aovs'], observed['color_configuration_fact']['products'][0]['ordered_vars']['forwarded_targets'])
                self.assertTrue(observed['camera'].startswith('/'))

    def test_truncated_aov_capture_cannot_pass_render_preflight(self):
        with built_scene(native.SUPPORTED_VERSIONS[0], native.LIGHTING) as (addon, configuration):
            original = api.Prim.GetRelationship

            def relation(prim, name):
                actual = original(prim, name)
                if name == 'orderedVars' and actual:
                    actual.GetTargets = actual.GetForwardedTargets = lambda: ['/Vars/aov' + str(i) for i in range(129)]
                return actual

            original_prim = api.Stage.GetPrimAtPath
            def prim(stage, path):
                if str(path).startswith('/Vars/aov'):
                    return api.Prim(str(path), 'RenderVar')
                return original_prim(stage, path)

            with patch.object(api.Prim, 'GetRelationship', relation), patch.object(api.Stage, 'GetPrimAtPath', prim):
                with self.assertRaises(addon.BridgeCommandError) as error:
                    configuration({}, [1])
            self.assertEqual(error.exception.code, 'RENDER_CONFIG_INVALID')

    def test_light_search_stops_at_native_prim_limit(self):
        from houdini_bridge.render_color_facts import MAX_OBSERVATION_VALUES
        with built_scene(native.SUPPORTED_VERSIONS[0], native.LIGHTING) as (addon, configuration):
            visited = []
            def traverse(stage):
                for index in range(MAX_OBSERVATION_VALUES + 2):
                    visited.append(index)
                    if index > MAX_OBSERVATION_VALUES:
                        raise AssertionError('unbounded native traversal')
                    yield api.Prim('/World/item' + str(index), 'Xform')
            with patch.object(api.Stage, 'Traverse', traverse):
                with self.assertRaises(addon.BridgeCommandError) as error:
                    configuration({}, [1])
            self.assertEqual(error.exception.code, 'RENDER_CONFIG_INVALID')
            self.assertEqual(len(visited), MAX_OBSERVATION_VALUES + 1)

    def test_all_frames_share_one_capture_budget_before_stage_export(self):
        for version in native.SUPPORTED_VERSIONS:
            with self.subTest(version=version), built_scene(version, native.LIGHTING) as (addon, configuration):
                driver = dict(zip(configuration.__code__.co_freevars,
                                  (cell.cell_contents for cell in configuration.__closure__)))['driver']
                hou = sys.modules['hou']
                terminal = hou.node(driver.parm('loppath').eval())
                original_stage = type(terminal).stage
                exports, captures = [], []

                def stage(node, *arguments, **keywords):
                    observed = original_stage(node, *arguments, **keywords)
                    if node is terminal:
                        captures.append(keywords['frame'])
                        settings = observed.GetPrimAtPath(driver.parm('rendersettings').eval())
                        settings.relations['husk:orderedImageFilters'] = ['/Filters/payload']
                        shader = api.Prim('/Filters/payload', 'Shader')
                        shader.attributes = {
                            'inputs:payload' + str(index): api.Attribute(
                                'string', 'X' * 8192, 'inputs:payload' + str(index))
                            for index in range(32)}
                        observed.prims[shader.path] = shader
                        export = observed.ExportToString
                        observed.ExportToString = lambda: (exports.append(keywords['frame']), export())[1]
                    return observed

                with patch.object(type(terminal), 'stage', stage):
                    with self.assertRaises(addon.BridgeCommandError) as error:
                        addon._fx_render_configuration(driver, list(range(1, 13)))
                self.assertEqual(error.exception.code, 'RENDER_CONFIG_INVALID')
                self.assertLess(len(captures), 12)
                self.assertEqual(exports, captures[:-1], 'refuse known oversize before native USD export')

    def test_requested_frames_match_sampled_exr_and_color_observations(self):
        observations = {}
        expected = {}
        for version in native.SUPPORTED_VERSIONS:
            for domain in (native.LIGHTING, native.MATERIAL):
                with built_scene(version, domain) as (_, configuration):
                    frames = [1, 1.25, 2]
                    attributes = {
                        "storage": SampledAttribute("string", "scanline", PREFIX + "storage",
                                                    dict.fromkeys(frames, "scanline")),
                        "multipart": SampledAttribute("int", 0, PREFIX + "multipart",
                                                      dict.fromkeys(frames, 0)),
                        "compression": SampledAttribute("string", "none", PREFIX + "compression",
                                                        {1: "zip", 1.25: "zips", 2: "none"}),
                    }
                    product_name = SampledAttribute("token", "/default.exr", "productName",
                                                    {frame: "/sample-" + str(frame) + ".exr"
                                                     for frame in frames})
                    result = configuration({**attributes, "productName": product_name}, frames)
                    for frame in frames:
                        actual = result[str(frame)]
                        color = actual["color_configuration_fact"]["products"][0]["attributes"]
                        observed_color = color["productName"]["value"]
                        identity = (version, domain, frame)
                        observations[identity] = (actual["exr_format"], observed_color)
                        sampled = {key: attribute.samples[frame] for key, attribute in attributes.items()}
                        expected[identity] = (sampled, product_name.samples[frame])
        self.assertEqual(observations, expected)

    def test_unsupported_sample_is_refused_despite_valid_default(self):
        for version in native.SUPPORTED_VERSIONS:
            for domain in (native.LIGHTING, native.MATERIAL):
                with built_scene(version, domain) as (addon, configuration):
                    for key, kind, default, unsupported in (
                        ("storage", "string", "scanline", "tiled"),
                        ("multipart", "int", 0, 1),
                        ("compression", "string", "zip", "piz"),
                    ):
                        with self.subTest(version=version, domain=domain, field=key):
                            attribute = SampledAttribute(kind, default, PREFIX + key,
                                                         {1.25: unsupported})
                            with self.assertRaises(addon.BridgeCommandError) as error:
                                configuration({key: attribute}, [1.25])
                            self.assertEqual(error.exception.code, "RENDER_CONFIG_INVALID")

    def test_invalid_native_values_and_exceptions_are_command_errors(self):
        for version in native.SUPPORTED_VERSIONS:
            for domain in (native.LIGHTING, native.MATERIAL):
                with built_scene(version, domain) as (addon, configuration):
                    for label, key, kind, value, native_error in (
                        ("bool-is-not-int", "multipart", "int", False, None),
                        ("float-is-not-int", "multipart", "int", 0.0, None),
                        ("wrong-value-type", "compression", "string", 0, None),
                        ("wrong-usd-type", "compression", "int", "zip", None),
                        ("unhashable-list", "compression", "string", [], None),
                        ("unhashable-map", "storage", "string", {}, None),
                        ("missing-value", "compression", "string", None, None),
                        ("native-get-error", "compression", "string", "zip",
                         RuntimeError("explicit native Attribute.Get failure")),
                    ):
                        with self.subTest(version=version, domain=domain, case=label):
                            attribute = SampledAttribute(kind, value, PREFIX + key,
                                                         {1.25: value}, error=native_error)
                            with self.assertRaises(addon.BridgeCommandError) as error:
                                configuration({key: attribute}, [1.25])
                            self.assertEqual(error.exception.code, "RENDER_CONFIG_INVALID")

    def test_validated_value_is_not_read_again_for_storage(self):
        for version in native.SUPPORTED_VERSIONS:
            for domain in (native.LIGHTING, native.MATERIAL):
                with built_scene(version, domain) as (_, configuration):
                    attribute = SampledAttribute("string", "zip", PREFIX + "compression",
                                                 {1.25: "zips"}, drift=True)
                    observed = configuration({"compression": attribute}, [1.25])["1.25"]
                    self.assertEqual(observed["exr_format"]["compression"], "zips")
                    self.assertEqual(attribute.calls, [1.25],
                                     "validate and store the same single sampled native value")


if __name__ == "__main__":
    unittest.main()
