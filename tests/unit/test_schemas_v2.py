from __future__ import annotations

import unittest

from dcc_task_runtime import PUBLIC_JSON_SCHEMAS, all_public_json_schemas, public_json_schema


class PublicSchemaTests(unittest.TestCase):
    def test_required_model_boundaries_export_strict_schemas(self) -> None:
        expected = {"task_spec_v2", "task_spec_v21", "planner_action", "vision_analysis", "evidence_bundle", "candidate_patch", "approval_request"}
        self.assertEqual(set(PUBLIC_JSON_SCHEMAS), expected)
        for name, schema in all_public_json_schemas().items():
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertEqual(schema["type"], "object")
            self.assertFalse(schema["additionalProperties"])
            self.assertTrue(schema["required"], name)

    def test_schema_export_is_a_copy(self) -> None:
        schema = public_json_schema("planner_action")
        schema["properties"]["tool"]["type"] = "integer"
        self.assertNotEqual(public_json_schema("planner_action")["properties"]["tool"]["type"], "integer")


if __name__ == "__main__":
    unittest.main()
