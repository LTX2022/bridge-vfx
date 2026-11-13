"""Bottom USD object API substitutes only; no facade, DCC or renderer executes."""
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/houdini-bridge/src"))

from houdini_bridge.render_color_facts import collect_render_color_facts


class Attribute:
    def __init__(self, name, type_name, value, samples=None, authored=True):
        self.name = name
        self.type_name = type_name
        self.value = value
        self.samples = samples or {}
        self.authored = authored
        self.read_frames = []

    def GetName(self):
        return self.name

    def GetTypeName(self):
        return self.type_name

    def HasAuthoredValueOpinion(self):
        return self.authored

    def Get(self, frame):
        self.read_frames.append(frame)
        return self.samples.get(frame, self.value)


class Relationship:
    def __init__(self, targets, forwarded=None):
        self.targets = list(targets)
        self.forwarded = list(targets if forwarded is None else forwarded)

    def GetTargets(self):
        return list(self.targets)

    def GetForwardedTargets(self):
        return list(self.forwarded)


class NativePath:
    def __init__(self, path, *, absolute=True, prim=True, property_path=False, variants=False):
        self.path = path
        self.absolute = absolute
        self.prim = prim
        self.property_path = property_path
        self.variants = variants

    def __str__(self):
        return self.path

    def IsAbsolutePath(self):
        return self.absolute

    def IsPrimPath(self):
        return self.prim

    def IsPrimPropertyPath(self):
        return self.property_path

    def ContainsPrimVariantSelection(self):
        return self.variants


class Prim:
    def __init__(self, path, type_name, attributes=None, relationships=None):
        self.path = path
        self.type_name = type_name
        self.attributes = attributes or {}
        self.relationships = relationships or {}

    def GetPath(self):
        return self.path

    def GetTypeName(self):
        return self.type_name

    def IsActive(self):
        return True

    def GetAttribute(self, name):
        return self.attributes.get(name)

    def GetAttributes(self):
        return list(self.attributes.values())

    def GetRelationship(self, name):
        return self.relationships.get(name)


class Stage:
    def __init__(self, prims):
        self.prims = {prim.path: prim for prim in prims}
        self.lookups = []

    def GetPrimAtPath(self, path):
        self.lookups.append(path)
        return self.prims.get(path)


def usd_stage():
    settings = Prim("/Render/settings", "RenderSettings", {
        "renderingColorSpace": Attribute("renderingColorSpace", "token", "working-role"),
    }, {"products": Relationship(["/Render/output"]),
        "husk:orderedImageFilters": Relationship(["/Filters/second", "/Filters/first"])})
    product = Prim("/Render/output", "RenderProduct", {
        "productName": Attribute("productName", "token", "relative/output.exr"),
        "productType": Attribute("productType", "token", "raster"),
    }, {"orderedVars": Relationship(["/Vars/beauty", "/Vars/alpha"])})
    beauty = Prim("/Vars/beauty", "RenderVar", {
        "sourceName": Attribute("sourceName", "string", "C"),
        "sourceType": Attribute("sourceType", "token", "raw"),
        "dataType": Attribute("dataType", "token", "color3f"),
        "driver:parameters:aov:husk:output_colorspace": Attribute(
            "driver:parameters:aov:husk:output_colorspace", "string", "destination-role"),
    })
    alpha = Prim("/Vars/alpha", "RenderVar", {
        "sourceName": Attribute("sourceName", "string", "A"),
        "sourceType": Attribute("sourceType", "token", "raw"),
        "dataType": Attribute("dataType", "token", "float"),
    })
    filters = [Prim("/Filters/second", "Shader", {
        "info:id": Attribute("info:id", "token", "observed-filter-2")}),
        Prim("/Filters/first", "Shader", {
        "inputs:gain": Attribute("inputs:gain", "float", 1.25)})]
    return Stage([settings, product, beauty, alpha, *filters])


class RenderColorFactsTests(unittest.TestCase):
    def test_native_exception_body_is_never_retained(self):
        stage = usd_stage()
        message = "explicit-native-error-fixture:" + "X" * 131072
        def failed_get(frame):
            raise RuntimeError(message)
        stage.prims["/Vars/beauty"].attributes["sourceName"].Get = failed_get
        facts = self.collect(stage)
        gap = next(item for item in facts["missing_facts"]
                   if item["code"] == "ATTRIBUTE_READ_FAILED")
        self.assertLessEqual(len(gap["detail"]), 256)
        self.assertNotIn("explicit-native-error-fixture:", json.dumps(facts))
        self.assertNotIn("value", facts["products"][0]["vars"][0]["attributes"]["sourceName"])
        self.assertTrue(any(item["code"] == "ALPHA_ASSOCIATION_UNPROVEN"
                            for item in facts["missing_facts"]))

    def test_legal_filter_arrays_share_a_total_payload_budget(self):
        stage = usd_stage()
        reads = []
        class NativeArray:
            def __len__(self):
                return 128
            def __getitem__(self, index):
                reads.append(index)
                return "X" * 8192
        stage.prims["/Filters/first"].attributes = {
            "inputs:payload_" + str(index): Attribute(
                "inputs:payload_" + str(index), "token[]", NativeArray())
            for index in range(4)}
        with self.assertRaisesRegex(ValueError, "observation budget"):
            self.collect(stage)
        self.assertLessEqual(len(reads), 256)
        self.assertEqual(stage.prims["/Filters/first"].attributes["inputs:payload_2"].read_frames, [])

    def test_budget_counts_json_escaping_and_nonascii_before_array_copy(self):
        for text in ('"' * 8192, '\\' * 8192, '\x00' * 8192, '\U0001f600' * 8192):
            with self.subTest(character=repr(text[0])):
                reads = []
                class NativeArray:
                    def __len__(self):
                        return 128
                    def __getitem__(self, index):
                        reads.append(index)
                        return text
                stage = usd_stage()
                stage.prims["/Filters/first"].attributes = {
                    "inputs:data": Attribute("inputs:data", "token[]", NativeArray())}
                with self.assertRaisesRegex(ValueError, "observation budget"):
                    self.collect(stage)
                self.assertLessEqual(len(reads), 128)

    def test_global_value_work_budget_aborts_across_filters(self):
        stage = usd_stage()
        for path in ("/Filters/first", "/Filters/second"):
            stage.prims[path].attributes = {
                "inputs:data_" + str(index): Attribute(
                    "inputs:data_" + str(index), "bool[]", [False] * 128)
                for index in range(64)}
        with self.assertRaisesRegex(ValueError, "observation budget"):
            self.collect(stage)

    def test_gaps_and_structure_share_the_observation_budget(self):
        for mode in ("gaps", "structure"):
            with self.subTest(mode=mode):
                stage = usd_stage()
                paths = []
                for index in range(128):
                    path = "/Filters/filter_" + str(index)
                    paths.append(path)
                    stage.prims[path] = Prim(path, "Shader", {
                        "inputs:item_" + str(number): Attribute(
                            "inputs:item_" + str(number), "X" * 8192 if mode == "gaps" else "bool",
                            False) for number in range(64)})
                stage.prims["/Render/settings"].relationships["husk:orderedImageFilters"] = Relationship(paths)
                with self.assertRaisesRegex(ValueError, "observation budget"):
                    self.collect(stage)
                self.assertLess(len(stage.lookups), 129)

    def test_native_names_and_types_are_bounded_at_each_capture_boundary(self):
        for mode in ("attribute_name", "attribute_type", "prim_type", "prim_path", "filter_name"):
            with self.subTest(mode=mode):
                stage = usd_stage()
                huge = "X" * 131072
                prim = stage.prims["/Vars/beauty"]
                if mode == "attribute_name":
                    prim.attributes["sourceName"].name = huge
                elif mode == "attribute_type":
                    prim.attributes["sourceName"].type_name = huge
                elif mode == "prim_type":
                    prim.type_name = huge
                elif mode == "prim_path":
                    prim.path = huge
                else:
                    stage.prims["/Filters/first"].attributes = {
                        huge: Attribute(huge, "token", "x")}
                with self.assertRaisesRegex(ValueError, "observation budget"):
                    self.collect(stage)

    def test_native_exceptions_at_all_read_boundaries_do_not_format_bodies(self):
        class NativeFailure(RuntimeError):
            def __str__(self):
                raise AssertionError("native exception body must not be formatted")
        def failed_read(*args):
            raise NativeFailure("sensitive native exception fixture")
        for mode in ("attribute", "relationship", "prim", "filter", "value_error"):
            with self.subTest(mode=mode):
                stage = usd_stage()
                if mode == "attribute":
                    stage.prims["/Vars/beauty"].attributes["sourceName"].Get = failed_read
                elif mode == "relationship":
                    stage.prims["/Render/settings"].relationships["products"].GetTargets = failed_read
                elif mode == "prim":
                    stage.prims["/Vars/beauty"].GetTypeName = failed_read
                elif mode == "filter":
                    stage.prims["/Filters/first"].GetAttributes = failed_read
                else:
                    def failed_value(frame):
                        raise ValueError("sensitive native exception fixture")
                    stage.prims["/Vars/beauty"].attributes["sourceName"].Get = failed_value
                facts = self.collect(stage)
                self.assertNotIn("sensitive native", json.dumps(facts))
                self.assertTrue(any(item["code"] == "ALPHA_ASSOCIATION_UNPROVEN"
                                    for item in facts["missing_facts"]))

    def test_filter_enumeration_uses_checked_indexed_access(self):
        stage = usd_stage()
        attribute = stage.prims["/Filters/first"].attributes["inputs:gain"]
        class NativeAttributes:
            def __len__(self):
                return 1
            def __getitem__(self, index):
                if index != 0:
                    raise AssertionError("unchecked index")
                return attribute
            def __iter__(self):
                raise AssertionError("unbounded iterator must not be used")
        stage.prims["/Filters/first"].GetAttributes = lambda: NativeAttributes()
        facts = self.collect(stage)
        self.assertEqual(facts["settings"]["image_filters"]["ordered_filters"][1]
                         ["attributes"]["inputs:gain"]["value"], 1.25)

    def test_seventeen_aovs_and_legal_values_preserve_normal_facts(self):
        stage = usd_stage()
        paths = []
        for index in range(17):
            path = "/Vars/aov_" + str(index)
            paths.append(path)
            attributes = {
                name: Attribute(name, attribute.type_name, attribute.value,
                                samples=attribute.samples, authored=attribute.authored)
                for name, attribute in stage.prims["/Vars/beauty"].attributes.items()}
            attributes["sourceName"] = Attribute("sourceName", "string", '\U0001f600"\\\n')
            stage.prims[path] = Prim(path, "RenderVar", attributes)
        stage.prims["/Render/output"].relationships["orderedVars"] = Relationship(paths)
        facts = self.collect(stage)
        self.assertEqual(len(facts["products"][0]["vars"]), 17)
        self.assertTrue(all(item["attributes"]["sourceName"]["value"] == '\U0001f600"\\\n'
                            for item in facts["products"][0]["vars"]))
        for ensure_ascii in (True, False):
            self.assertLessEqual(len(json.dumps(facts, ensure_ascii=ensure_ascii,
                                               allow_nan=False).encode("utf-8")), 2 * 1024 * 1024)

    def collect(self, stage=None, frame=1):
        return collect_render_color_facts(stage or usd_stage(), frame=frame,
                                          settings_path="/Render/settings")

    def test_reads_actual_relations_types_values_and_filter_order(self):
        stage = usd_stage()
        facts = self.collect(stage)
        self.assertEqual(stage.lookups, ["/Render/settings", "/Filters/second",
            "/Filters/first", "/Render/output", "/Vars/beauty", "/Vars/alpha"])
        self.assertEqual(facts["settings"]["products"]["targets"], ["/Render/output"])
        product = facts["products"][0]
        self.assertEqual([item["path"] for item in product["vars"]], ["/Vars/beauty", "/Vars/alpha"])
        self.assertEqual(product["attributes"]["productName"]["value"], "relative/output.exr")
        output = product["vars"][0]["attributes"]["driver:parameters:aov:husk:output_colorspace"]
        self.assertEqual(output, {"present": True, "type_name": "string",
                                  "authored": True, "value": "destination-role"})
        filters = facts["settings"]["image_filters"]["ordered_filters"]
        self.assertEqual([item["path"] for item in filters], ["/Filters/second", "/Filters/first"])
        self.assertEqual(filters[1]["attributes"]["inputs:gain"]["value"], 1.25)
        json.dumps(facts, allow_nan=False)

    def test_product_color_fields_are_sampled_independently_of_aov_overrides(self):
        stage = usd_stage()
        product = stage.prims['/Render/output']
        for name, value in (('source_colorspace', 'product-source'), ('output_colorspace', 'product-output')):
            key = 'driver:parameters:husk:' + name
            product.attributes[key] = Attribute(key, 'string', value, samples={3: value + '-frame3'})
        first = self.collect(stage, frame=1)
        last = self.collect(stage, frame=3)
        for name, value in (('source_colorspace', 'product-source'), ('output_colorspace', 'product-output')):
            key = 'driver:parameters:husk:' + name
            self.assertEqual(first['products'][0]['attributes'][key]['value'], value)
            self.assertEqual(last['products'][0]['attributes'][key]['value'], value + '-frame3')
        self.assertEqual(first['products'][0]['vars'][0]['attributes'][
            'driver:parameters:aov:husk:output_colorspace']['value'], 'destination-role')
        self.assertTrue(any(item['code'] == 'ALPHA_ASSOCIATION_UNPROVEN' for item in first['missing_facts']))
        self.assertNotIn('metadata', first)

    def test_absent_product_color_fields_are_missing_without_inheritance_defaults(self):
        facts = self.collect()
        for name in ('source_colorspace', 'output_colorspace'):
            key = 'driver:parameters:husk:' + name
            self.assertEqual(facts['products'][0]['attributes'][key], {'present': False})
            self.assertTrue(any(item['code'] == 'ATTRIBUTE_MISSING'
                                and item['path'] == '/Render/output.' + key for item in facts['missing_facts']))

    def test_product_and_var_color_fields_require_native_string_schema(self):
        for path, prefix in (('/Render/output', 'driver:parameters:husk:'),
                             ('/Vars/beauty', 'driver:parameters:aov:husk:')):
            for name in ('source_colorspace', 'output_colorspace'):
                stage = usd_stage()
                key = prefix + name
                stage.prims[path].attributes[key] = Attribute(key, 'token', 'a-token')
                facts = self.collect(stage)
                observed = facts['products'][0]
                attributes = observed['attributes'] if path == '/Render/output' else observed['vars'][0]['attributes']
                with self.subTest(path=path, name=name):
                    self.assertNotIn('value', attributes[key])
                    self.assertTrue(any(item['code'] == 'ATTRIBUTE_TYPE_UNSUPPORTED'
                                        and item['path'] == path + '.' + key for item in facts['missing_facts']))

    def test_aov_filter_format_and_channel_naming_are_sampled_per_var_and_frame(self):
        stage = usd_stage()
        samples = {
            "driver:parameters:aov:karma:filter": ("string", '["ubox",{}]', '["minmax",{"mode":"min"}]'),
            "driver:parameters:aov:husk:format": ("token", "color3h", "color3f"),
            "driver:parameters:aov:husk:channel_prefix": ("string", "diffuse", "beauty"),
            "driver:parameters:aov:husk:channel_lower_rgb": ("bool", False, True),
        }
        beauty = stage.prims["/Vars/beauty"]
        alpha = stage.prims["/Vars/alpha"]
        for name, (type_name, first_value, last_value) in samples.items():
            beauty.attributes[name] = Attribute(name, type_name, None,
                samples={1: first_value, 3: last_value})
            alpha.attributes[name] = Attribute(name, type_name, first_value, authored=False)
        for frame in (1, 3):
            facts = self.collect(stage, frame)
            variables = facts["products"][0]["vars"]
            for name, (type_name, first_value, last_value) in samples.items():
                with self.subTest(frame=frame, name=name):
                    self.assertEqual(variables[0]["attributes"][name], {
                        "present": True, "type_name": type_name, "authored": True,
                        "value": first_value if frame == 1 else last_value})
                    self.assertEqual(variables[1]["attributes"][name], {
                        "present": True, "type_name": type_name, "authored": False,
                        "value": first_value})
                    self.assertFalse(any(item["path"] == "/Vars/beauty." + name
                        or item["path"] == "/Vars/alpha." + name for item in facts["missing_facts"]))
        for name in samples:
            self.assertEqual(beauty.attributes[name].read_frames, [1, 3])
            self.assertEqual(alpha.attributes[name].read_frames, [1, 3])

    def test_aov_output_properties_distinguish_absent_none_and_empty_without_defaults(self):
        for name, type_name in (
            ("driver:parameters:aov:karma:filter", "string"),
            ("driver:parameters:aov:husk:format", "token"),
            ("driver:parameters:aov:husk:channel_prefix", "string"),
            ("driver:parameters:aov:husk:channel_lower_rgb", "bool"),
        ):
            cases = [("absent", None, "ATTRIBUTE_MISSING"),
                     ("none", None, "ATTRIBUTE_VALUE_MISSING")]
            if type_name != "bool":
                cases.append(("empty", "", "ATTRIBUTE_VALUE_EMPTY"))
            for mode, value, code in cases:
                with self.subTest(name=name, mode=mode):
                    stage = usd_stage()
                    if mode != "absent":
                        stage.prims["/Vars/beauty"].attributes[name] = Attribute(
                            name, type_name, value, authored=False)
                    facts = self.collect(stage)
                    observation = facts["products"][0]["vars"][0]["attributes"][name]
                    expected = {"present": False} if mode == "absent" else {
                        "present": True, "type_name": type_name, "authored": False}
                    self.assertEqual(observation, expected)
                    gaps = {(item["code"], item["path"]) for item in facts["missing_facts"]}
                    self.assertIn((code, "/Vars/beauty." + name), gaps)

    def test_aov_output_properties_reject_wrong_native_types_and_payload_types(self):
        cases = [
            ("driver:parameters:aov:karma:filter", "token", '["ubox",{}]', False),
            ("driver:parameters:aov:karma:filter", "string[]", ["ubox"], False),
            ("driver:parameters:aov:karma:filter", "string", ["ubox", {}], True),
            ("driver:parameters:aov:husk:format", "string", "color3h", False),
            ("driver:parameters:aov:husk:format", "token", 1, True),
            ("driver:parameters:aov:husk:channel_prefix", "token", "diffuse", False),
            ("driver:parameters:aov:husk:channel_lower_rgb", "int", 1, False),
            ("driver:parameters:aov:husk:channel_lower_rgb", "bool", 1, True),
        ]
        for name, type_name, value, read_value in cases:
            with self.subTest(name=name, type_name=type_name, value=value):
                stage = usd_stage()
                attribute = Attribute(name, type_name, value)
                stage.prims["/Vars/beauty"].attributes[name] = attribute
                facts = self.collect(stage)
                self.assertEqual(facts["products"][0]["vars"][0]["attributes"][name], {
                    "present": True, "type_name": type_name, "authored": True})
                self.assertEqual(attribute.read_frames, [1] if read_value else [])
                self.assertTrue(any(item["code"] == "ATTRIBUTE_TYPE_UNSUPPORTED" and
                    item["path"] == "/Vars/beauty." + name for item in facts["missing_facts"]))
                json.dumps(facts, allow_nan=False)

    def test_aov_output_strings_use_existing_bounded_capture(self):
        for name, type_name in (
            ("driver:parameters:aov:karma:filter", "string"),
            ("driver:parameters:aov:husk:format", "token"),
            ("driver:parameters:aov:husk:channel_prefix", "string"),
        ):
            for size in (8192, 8193):
                with self.subTest(name=name, size=size):
                    stage = usd_stage()
                    value = "x" * size
                    stage.prims["/Vars/beauty"].attributes[name] = Attribute(name, type_name, value)
                    facts = self.collect(stage)
                    observation = facts["products"][0]["vars"][0]["attributes"][name]
                    gaps = [item for item in facts["missing_facts"] if item["path"] == "/Vars/beauty." + name]
                    if size == 8192:
                        self.assertEqual(observation["value"], value)
                        self.assertEqual(gaps, [])
                    else:
                        self.assertNotIn("value", observation)
                        self.assertEqual([item["code"] for item in gaps], ["ATTRIBUTE_TYPE_UNSUPPORTED"])

    def test_corrupted_aov_filter_payload_is_preserved_raw_without_execution_claims(self):
        stage = usd_stage()
        name = "driver:parameters:aov:karma:filter"
        payload = '["minmax",{"mode":"min"}'
        with self.assertRaises(json.JSONDecodeError):
            json.loads(payload)
        stage.prims["/Vars/beauty"].attributes[name] = Attribute(name, "string", payload)
        facts = self.collect(stage)
        self.assertEqual(facts["products"][0]["vars"][0]["attributes"][name], {
            "present": True, "type_name": "string", "authored": True, "value": payload})
        self.assertFalse(any(item["path"] == "/Vars/beauty." + name for item in facts["missing_facts"]))
        codes = {item["code"] for item in facts["missing_facts"]}
        self.assertTrue({"OCIO_CONFIGURATION_UNRESOLVED", "RUNTIME_OVERRIDES_UNOBSERVED",
            "IMAGE_FILTER_EXECUTION_UNOBSERVED", "ALPHA_ASSOCIATION_UNPROVEN"} <= codes)
        encoded = json.dumps(facts, allow_nan=False)
        for forbidden in ('"metadata"', '"executed"', '"status"', "AVAILABLE", "PASS", "premultiplied"):
            self.assertNotIn(forbidden, encoded)

    def test_help_anchor_and_unverified_channel_layout_are_not_native_usd_facts(self):
        stage = usd_stage()
        attributes = stage.prims["/Vars/beauty"].attributes
        for name in ("karma:plane:filter", "driver:parameters:aov:husk:channel_layout"):
            attributes[name] = Attribute(name, "string", "unverified-alias")
        facts = self.collect(stage)
        observations = facts["products"][0]["vars"][0]["attributes"]
        self.assertEqual(observations["driver:parameters:aov:karma:filter"], {"present": False})
        self.assertNotIn("karma:plane:filter", observations)
        self.assertNotIn("driver:parameters:aov:husk:channel_layout", observations)
        self.assertTrue(any(item["code"] == "ATTRIBUTE_MISSING" and
            item["path"] == "/Vars/beauty.driver:parameters:aov:karma:filter"
            for item in facts["missing_facts"]))

    def test_each_frame_reads_sample_and_new_composed_relationships(self):
        stage = usd_stage()
        attribute = stage.prims["/Vars/beauty"].attributes["driver:parameters:aov:husk:output_colorspace"]
        attribute.samples = {1: "first-space", 2: "second-space"}
        first = self.collect(stage, 1)
        stage.prims["/Render/output"].relationships["orderedVars"] = Relationship(["/Vars/beauty"])
        second = self.collect(stage, 2)
        self.assertEqual(attribute.read_frames, [1, 2])
        key = "driver:parameters:aov:husk:output_colorspace"
        self.assertEqual(first["products"][0]["vars"][0]["attributes"][key]["value"], "first-space")
        self.assertEqual(second["products"][0]["vars"][0]["attributes"][key]["value"], "second-space")
        self.assertEqual(len(first["products"][0]["vars"]), 2)
        self.assertEqual(len(second["products"][0]["vars"]), 1)

    def test_missing_values_have_exact_paths_without_color_or_alpha_defaults(self):
        facts = self.collect()
        gaps = {(item["code"], item["path"]) for item in facts["missing_facts"]}
        self.assertIn(("ATTRIBUTE_MISSING", "/Vars/alpha.driver:parameters:aov:husk:output_colorspace"), gaps)
        for code in ("OCIO_CONFIGURATION_UNRESOLVED", "RUNTIME_OVERRIDES_UNOBSERVED",
                     "ALPHA_ASSOCIATION_UNPROVEN"):
            self.assertIn((code, "/Render/settings"), gaps)
        self.assertIn(("OUTPUT_PATH_UNRESOLVED", "/Render/output.productName"), gaps)
        encoded = json.dumps(facts)
        for forbidden in ("scene_linear", "premultiplied", "AVAILABLE", "completion_metadata", '"status"'):
            self.assertNotIn(forbidden, encoded)

    def test_missing_relationship_and_wrong_target_type_do_not_invent_vars(self):
        stage = usd_stage()
        del stage.prims["/Render/output"].relationships["orderedVars"]
        facts = self.collect(stage)
        self.assertEqual(facts["products"][0]["vars"], [])
        self.assertTrue(any(item["path"] == "/Render/output.orderedVars" and
                            item["code"] == "RELATIONSHIP_MISSING" for item in facts["missing_facts"]))
        stage.prims["/Render/settings"].relationships["products"] = Relationship(["/Vars/beauty", "/missing"])
        facts = self.collect(stage)
        self.assertEqual(facts["products"], [])
        self.assertEqual([item["code"] for item in facts["missing_facts"] if
                          item["path"] in {"/Vars/beauty", "/missing"}],
                         ["PRIM_TYPE_UNSUPPORTED", "PRIM_MISSING"])

    def test_forwarded_targets_preserve_raw_relationship_order(self):
        stage = usd_stage()
        stage.prims["/Render/settings"].relationships["products"] = Relationship(
            ["/Links.outputs"], ["/Render/output"])
        facts = self.collect(stage)
        relation = facts["settings"]["products"]
        self.assertEqual(relation["targets"], ["/Links.outputs"])
        self.assertEqual(relation["forwarded_targets"], ["/Render/output"])
        self.assertEqual(facts["products"][0]["path"], "/Render/output")

    def test_filter_attribute_preserves_order_without_inventing_relationship(self):
        stage = usd_stage()
        settings = stage.prims["/Render/settings"]
        del settings.relationships["husk:orderedImageFilters"]
        settings.attributes["husk:orderedImageFilters"] = Attribute(
            "husk:orderedImageFilters", "token[]", ["/Filters/second", "/Filters/first"])
        facts = self.collect(stage)
        filters = facts["settings"]["image_filters"]
        self.assertFalse(filters["relationship"]["present"])
        self.assertEqual(filters["attribute"]["value"], ["/Filters/second", "/Filters/first"])
        self.assertEqual(filters["ordered_filters"], [])
        self.assertNotIn("/Filters/second", stage.lookups)
        self.assertTrue(any(item["code"] == "FILTER_PROPERTY_SEMANTICS_UNRESOLVED"
                            for item in facts["missing_facts"]))

    def test_forwarding_failure_retains_raw_targets_and_does_not_traverse(self):
        stage = usd_stage()
        relation = stage.prims["/Render/settings"].relationships["products"]
        def failed_forwarding():
            raise RuntimeError("unresolved relationship forwarding")
        relation.GetForwardedTargets = failed_forwarding
        facts = self.collect(stage)
        self.assertEqual(facts["settings"]["products"]["targets"], ["/Render/output"])
        self.assertEqual(facts["products"], [])
        self.assertNotIn("/Render/output", stage.lookups)
        self.assertTrue(any(item["code"] == "RELATIONSHIP_READ_FAILED"
                            for item in facts["missing_facts"]))

    def test_unsupported_type_none_empty_and_fallback_are_distinct(self):
        stage = usd_stage()
        attributes = stage.prims["/Vars/beauty"].attributes
        key = "driver:parameters:aov:husk:output_colorspace"
        attributes[key] = Attribute(key, "color3f", (1.0, 1.0, 1.0))
        attributes["sourceName"] = Attribute("sourceName", "string", None)
        attributes["sourceType"] = Attribute("sourceType", "token", "")
        attributes["dataType"].authored = False
        facts = self.collect(stage)
        observations = facts["products"][0]["vars"][0]["attributes"]
        self.assertEqual(observations[key]["type_name"], "color3f")
        self.assertNotIn("value", observations[key])
        self.assertFalse(observations["dataType"]["authored"])
        codes = {item["code"] for item in facts["missing_facts"]}
        self.assertTrue({"ATTRIBUTE_TYPE_UNSUPPORTED", "ATTRIBUTE_VALUE_MISSING", "ATTRIBUTE_VALUE_EMPTY"} <= codes)

    def test_native_karma_string_source_type_is_read_without_schema_coercion(self):
        stage = usd_stage()
        stage.prims["/Vars/beauty"].attributes["sourceType"] = Attribute("sourceType", "string", "lpe")
        facts = self.collect(stage)
        observed = facts["products"][0]["vars"][0]["attributes"]["sourceType"]
        self.assertEqual(observed["type_name"], "string")
        self.assertEqual(observed["value"], "lpe")
        self.assertFalse(any(item["path"] == "/Vars/beauty.sourceType"
                             for item in facts["missing_facts"]))

    def test_api_failure_is_recorded_and_targets_are_bounded(self):
        stage = usd_stage()
        attribute = stage.prims["/Vars/beauty"].attributes["sourceName"]
        def failed_get(frame):
            raise RuntimeError("bottom USD read failure")
        attribute.Get = failed_get
        facts = self.collect(stage)
        self.assertTrue(any(item["code"] == "ATTRIBUTE_READ_FAILED" and
                            "RuntimeError" in item["detail"] and
                            "bottom USD read failure" not in item["detail"] for item in facts["missing_facts"]))
        stage.prims["/Render/settings"].relationships["products"] = Relationship(["/Render/output"] * 129)
        stage.lookups.clear()
        facts = self.collect(stage)
        self.assertEqual(facts["products"], [])
        self.assertNotIn("/Render/output", stage.lookups)
        self.assertTrue(any(item["code"] == "RELATIONSHIP_LIMIT" for item in facts["missing_facts"]))

    def test_invalid_frame_and_settings_path_are_rejected_before_usd_access(self):
        stage = usd_stage()
        for frame in (True, float("nan"), float("inf"), "1"):
            with self.assertRaises(ValueError):
                self.collect(stage, frame)
        with self.assertRaises(ValueError):
            collect_render_color_facts(stage, frame=1, settings_path="relative")
        self.assertEqual(stage.lookups, [])

    def test_nested_targets_share_one_traversal_budget(self):
        stage = usd_stage()
        products = []
        variables = []
        for product_index in range(16):
            product_path = f"/Products/p{product_index}"
            var_paths = [f"/Vars/p{product_index}_v{var_index}" for var_index in range(16)]
            products.append(Prim(product_path, "RenderProduct", relationships={
                "orderedVars": Relationship(var_paths)}))
            variables.extend(Prim(path, "RenderVar") for path in var_paths)
        stage.prims.update({prim.path: prim for prim in [*products, *variables]})
        stage.prims["/Render/settings"].relationships["products"] = Relationship(
            [prim.path for prim in products])
        facts = self.collect(stage)
        self.assertLessEqual(len(stage.lookups) - 1, 128)
        self.assertTrue(any(item["code"] == "TRAVERSAL_LIMIT" for item in facts["missing_facts"]))
        json.dumps(facts, allow_nan=False)

    def test_invalid_absolute_settings_paths_fail_before_native_access(self):
        stage = usd_stage()
        for path in ("/", "/Render/settings.outputs", "/Render//settings", "/Render/../settings",
                     "/Render/settings/", "/Render/{variant=x}settings", "/Render/0settings",
                     "/Render/bad name", "/Render/bad\\name", "/Render/bad\x00name"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                collect_render_color_facts(stage, frame=1, settings_path=path)
        self.assertEqual(stage.lookups, [])

    def test_malformed_and_duplicate_relationships_do_not_traverse(self):
        cases = [(["/Render/output", "/Render/output"], None),
                 (["/Links.outputs"], ["/Render/output", "/Render/output"]),
                 (["/Render/output"], ["relative"]),
                 (["/Render/output"], ["/Render/output.attribute"]),
                 (["/Render/output"], ["/Render//output"]),
                 (["/Render/output"], ["/Render/../output"]),
                 (["/Render/output"], ["/Render/output/"]),
                 (["/Render/output"], ["/Render/{variant=x}output"]),
                 (["/Links..outputs"], ["/Render/output"]),
                 (["/Render/output"], [123]),
                 (["/Render/output"], ["/Render/output", "/bad name"])]
        for raw, forwarded in cases:
            with self.subTest(raw=raw, forwarded=forwarded):
                stage = usd_stage()
                stage.prims["/Render/settings"].relationships["products"] = Relationship(raw, forwarded)
                facts = self.collect(stage)
                self.assertEqual(facts["products"], [])
                self.assertEqual(facts["settings"]["products"]["forwarded_targets"], [])
                self.assertEqual(stage.lookups, ["/Render/settings", "/Filters/second", "/Filters/first"])
                self.assertTrue(any(item["path"] == "/Render/settings.products"
                                    for item in facts["missing_facts"]))

    def test_namespaced_forwarding_and_unicode_prim_paths_are_preserved(self):
        stage = usd_stage()
        product = stage.prims.pop("/Render/output")
        product.path = "/Render/输出_1"
        stage.prims[product.path] = product
        stage.prims["/Render/settings"].relationships["products"] = Relationship(
            ["/Links.outputs:render"], [product.path])
        facts = self.collect(stage)
        self.assertEqual(facts["settings"]["products"]["targets"], ["/Links.outputs:render"])
        self.assertEqual(facts["products"][0]["path"], product.path)

    def test_native_path_predicates_allow_forwarding_and_refuse_nonprim_targets(self):
        for target, accepted in ((NativePath("/Render/output"), True),
                                 (NativePath("output", absolute=False), False),
                                 (NativePath("/Render/output.attribute", prim=False, property_path=True), False),
                                 (NativePath("/Render/output{variant=x}", variants=True), False),
                                 (NativePath("/", prim=False), False)):
            with self.subTest(target=str(target)):
                stage = usd_stage()
                stage.prims["/Render/settings"].relationships["products"] = Relationship(
                    [NativePath("/Links.outputs:render", prim=False, property_path=True)], [target])
                facts = self.collect(stage)
                relation = facts["settings"]["products"]
                self.assertEqual(relation["targets"], ["/Links.outputs:render"])
                self.assertEqual(relation["forwarded_targets"], ["/Render/output"] if accepted else [])
                self.assertEqual(len(facts["products"]), 1 if accepted else 0)
                if not accepted:
                    self.assertTrue(any(item["code"] == "RELATIONSHIP_READ_FAILED" and
                        item["path"] == "/Render/settings.products" for item in facts["missing_facts"]))

    def test_filter_enumeration_failure_retains_products_and_other_filter(self):
        stage = usd_stage()
        def failed_attributes():
            raise RuntimeError("native filter enumeration failed")
        stage.prims["/Filters/second"].GetAttributes = failed_attributes
        facts = self.collect(stage)
        filters = facts["settings"]["image_filters"]["ordered_filters"]
        self.assertNotIn("attributes", filters[0])
        self.assertEqual(filters[1]["attributes"]["inputs:gain"]["value"], 1.25)
        self.assertEqual([item["path"] for item in facts["products"]], ["/Render/output"])
        self.assertTrue(any(item["code"] == "FILTER_READ_FAILED" and
            item["path"] == "/Filters/second" for item in facts["missing_facts"]))
        json.dumps(facts, allow_nan=False)

    def test_wrong_declared_schema_types_have_no_value(self):
        for type_name, value in (("bool", True), ("float", 1.25), ("token[]", ["working-role"])):
            with self.subTest(type_name=type_name):
                stage = usd_stage()
                attribute = Attribute("renderingColorSpace", type_name, value)
                stage.prims["/Render/settings"].attributes[attribute.name] = attribute
                facts = self.collect(stage)
                observation = facts["settings"]["attributes"][attribute.name]
                self.assertNotIn("value", observation)
                self.assertTrue(any(item["code"] == "ATTRIBUTE_TYPE_UNSUPPORTED" and
                    item["path"] == "/Render/settings.renderingColorSpace" for item in facts["missing_facts"]))

    def test_invalid_boolean_numeric_and_array_values_are_not_facts(self):
        cases = [("bool", 1), ("bool", "false"), ("int", True), ("int", 2**31),
                 ("int", -(2**31) - 1), ("int64", 2**63), ("uint", -1), ("uint", 2**32),
                 ("uint64", 2**64), ("float", True), ("float", 1e39),
                 ("double", 10**400), ("float", float("nan")), ("double", float("inf")),
                 ("token[]", {"working-role": 1}), ("token[]", {"working-role"}),
                 ("token[]", "working-role"), ("token[]", ["x"] * 129),
                 ("bool[]", [False, 1]), ("uint[]", [0, -1]),
                 ("float[][]", [[1.0]]), ("color3f[]", [])]
        for type_name, value in cases:
            with self.subTest(type_name=type_name, value=value):
                stage = usd_stage()
                attribute = Attribute("inputs:test", type_name, value)
                stage.prims["/Filters/first"].attributes = {attribute.name: attribute}
                facts = self.collect(stage)
                observation = facts["settings"]["image_filters"]["ordered_filters"][1]["attributes"][attribute.name]
                self.assertNotIn("value", observation)
                self.assertTrue(any(item["path"] == "/Filters/first.inputs:test"
                                    for item in facts["missing_facts"]))
                json.dumps(facts, allow_nan=False)

    def test_valid_numeric_boundaries_and_flat_arrays_remain_observable(self):
        cases = [("bool", False), ("int", -(2**31)), ("int", 2**31 - 1),
                 ("int64", -(2**63)), ("int64", 2**63 - 1), ("uint", 2**32 - 1),
                 ("uint64", 2**64 - 1), ("float", 3.4028234663852886e38),
                 ("double", 1.7976931348623157e308), ("bool[]", [False, True]),
                 ("float[]", (0.0, 1.25)), ("token[]", [])]
        for type_name, value in cases:
            with self.subTest(type_name=type_name):
                stage = usd_stage()
                attribute = Attribute("inputs:test", type_name, value)
                stage.prims["/Filters/first"].attributes = {attribute.name: attribute}
                facts = self.collect(stage)
                observation = facts["settings"]["image_filters"]["ordered_filters"][1]["attributes"][attribute.name]
                self.assertEqual(observation["value"], list(value) if isinstance(value, tuple) else value)
                self.assertFalse(any(item["path"] == "/Filters/first.inputs:test"
                                     for item in facts["missing_facts"]))

    def test_authored_flag_and_attribute_identity_are_not_coerced(self):
        for name, authored in (("renderingColorSpace", "false"), ("otherProperty", True)):
            with self.subTest(name=name, authored=authored):
                stage = usd_stage()
                stage.prims["/Render/settings"].attributes["renderingColorSpace"] = Attribute(
                    name, "token", "working-role", authored=authored)
                facts = self.collect(stage)
                observation = facts["settings"]["attributes"]["renderingColorSpace"]
                self.assertNotIn("value", observation)
                self.assertTrue(any(item["path"] == "/Render/settings.renderingColorSpace"
                                    for item in facts["missing_facts"]))

    def test_prim_type_is_sampled_once_and_failures_leave_partial_receipt(self):
        for path in ("/Render/settings", "/Render/output", "/Vars/beauty", "/Filters/first"):
            with self.subTest(path=path):
                stage = usd_stage()
                prim = stage.prims[path]
                type_name = prim.type_name
                calls = []
                def one_read_only():
                    calls.append(True)
                    if len(calls) > 1:
                        raise RuntimeError("second type query failed")
                    return type_name
                prim.GetTypeName = one_read_only
                facts = self.collect(stage)
                self.assertEqual(len(calls), 1)
                self.assertIn("missing_facts", facts)
                json.dumps(facts, allow_nan=False)

    def test_native_prim_errors_and_identity_mismatch_preserve_other_observations(self):
        for mode in ("type_error", "path_error", "wrong_path", "inactive"):
            with self.subTest(mode=mode):
                stage = usd_stage()
                prim = stage.prims["/Vars/beauty"]
                def failed_read():
                    raise RuntimeError("native prim query failed")
                if mode == "type_error":
                    prim.GetTypeName = failed_read
                elif mode == "path_error":
                    prim.GetPath = failed_read
                elif mode == "wrong_path":
                    prim.path = "/Vars/not_beauty"
                else:
                    prim.IsActive = lambda: False
                facts = self.collect(stage)
                self.assertEqual([item["path"] for item in facts["products"][0]["vars"]], ["/Vars/alpha"])
                self.assertTrue(any(item["path"] == "/Vars/beauty" for item in facts["missing_facts"]))


if __name__ == "__main__":
    unittest.main()
