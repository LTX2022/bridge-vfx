from __future__ import annotations

import math
import unittest

from dcc_task_runtime.graph_compiler import (
    CompiledGraph,
    GraphCompileError,
    GraphCompiler,
    GraphConnection,
    GraphContext,
    GraphNodeProposal,
    GraphOutput,
    GraphProposal,
    NodeSpec,
    ParameterSpec,
    PortSpec,
)


def _catalog(*, cycle_boundary: bool = False, plain_display: bool = False):
    boundary = not plain_display
    return {
        "source": NodeSpec(
            "source",
            outputs=(PortSpec("volume", "volume", boundary=boundary),),
            parameters=(
                ParameterSpec("density", "float", minimum=0.0, maximum=10.0, default=1.0),
                ParameterSpec("mode", "enum", enum_values=("smoke", "dust"), default="smoke"),
            ),
            allowed_contexts=("obj",),
            allow_subnet=True,
        ),
        "scalar": NodeSpec(
            "scalar",
            outputs=(PortSpec("value", "float", boundary=boundary),),
            allowed_contexts=("obj",),
        ),
        "shape": NodeSpec(
            "shape",
            inputs=(PortSpec("source", "volume", required=True, boundary=boundary),),
            outputs=(PortSpec("volume", "volume", boundary=boundary),),
            parameters=(ParameterSpec("steps", "int", minimum=1, maximum=32, default=4),),
            allowed_contexts=("obj", "stage"),
            allow_subnet=True,
        ),
        "merge": NodeSpec(
            "merge",
            inputs=(PortSpec("input", "volume", required=True, multiple=True, boundary=boundary),),
            outputs=(PortSpec("volume", "volume", boundary=boundary),),
            allowed_contexts=("obj", "stage"),
            allow_subnet=True,
        ),
        "display": NodeSpec(
            "display",
            inputs=(PortSpec("source", "volume", required=True, boundary=boundary),),
            outputs=(PortSpec("image", "image", boundary=boundary),),
            allowed_contexts=("obj", "stage"),
            allow_subnet=True,
        ),
        "loop": NodeSpec(
            "loop",
            inputs=(PortSpec("input", "volume", required=True),),
            outputs=(PortSpec("output", "volume"),),
            allowed_contexts=("obj",),
            cycle_boundary=cycle_boundary,
        ),
    }


def _contexts():
    return {
        "obj": GraphContext(
            "obj",
            allowed_node_types=("source", "scalar", "shape", "merge", "display", "loop"),
            allow_subnets=True,
            allowed_subnet_prefixes=(("sim",), ("comp",)),
        ),
        "stage": GraphContext(
            "stage",
            allowed_node_types=("shape", "merge", "display"),
            allow_subnets=True,
            allowed_subnet_prefixes=(("render",),),
        ),
    }


class GraphCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compiler = GraphCompiler(_catalog(), _contexts())

    def test_compilation_is_deterministic_and_applies_catalog_defaults(self) -> None:
        first = GraphProposal(
            nodes=(
                GraphNodeProposal("display", "display", context="obj"),
                GraphNodeProposal("shape", "shape", context="obj", parameters={"steps": 6}),
                GraphNodeProposal("source", "source", context="obj"),
            ),
            connections=(
                GraphConnection("shape", "volume", "display", "source"),
                GraphConnection("source", "volume", "shape", "source"),
            ),
            outputs=(GraphOutput("beauty", "display", "image"),),
        )
        second = GraphProposal(
            nodes=tuple(reversed(first.nodes)),
            connections=tuple(reversed(first.connections)),
            outputs=first.outputs,
        )

        compiled_first = self.compiler.compile(first)
        compiled_second = self.compiler.compile(second)
        compiled_roundtrip = self.compiler.compile(first.to_dict())

        self.assertIsInstance(compiled_first, CompiledGraph)
        self.assertEqual(compiled_first.to_dict(), compiled_second.to_dict())
        self.assertEqual(compiled_first.to_dict(), compiled_roundtrip.to_dict())
        self.assertEqual(compiled_first.nodes[2].parameters, {"density": 1.0, "mode": "smoke"})
        self.assertEqual(compiled_first.execution_order[0], "obj:/source")
        self.assertEqual(len(compiled_first.graph_hash), 64)

    def test_required_input_and_port_type_mismatch_are_structured(self) -> None:
        missing = GraphProposal(
            nodes=(GraphNodeProposal("shape", "shape", context="obj"),)
        )
        missing_codes = {item.code for item in self.compiler.validate(missing)}
        self.assertIn("MISSING_REQUIRED_INPUT", missing_codes)

        mismatch = GraphProposal(
            nodes=(
                GraphNodeProposal("scalar", "scalar", context="obj"),
                GraphNodeProposal("shape", "shape", context="obj"),
            ),
            connections=(GraphConnection("scalar", "value", "shape", "source"),),
        )
        mismatch_codes = {item.code for item in self.compiler.validate(mismatch)}
        self.assertIn("PORT_TYPE_MISMATCH", mismatch_codes)
        with self.assertRaises(GraphCompileError) as caught:
            self.compiler.compile(mismatch)
        self.assertEqual(caught.exception.code.value, "INVALID_STAGE_GRAPH")
        self.assertTrue(caught.exception.to_dict()["diagnostics"])

    def test_parameters_are_allowlisted_typed_finite_and_ranged(self) -> None:
        invalid = GraphProposal(
            nodes=(
                GraphNodeProposal(
                    "source",
                    "source",
                    context="obj",
                    parameters={"density": math.nan, "script": "raise()", "mode": "unknown"},
                ),
            )
        )
        codes = {item.code for item in self.compiler.validate(invalid)}
        self.assertTrue({"INVALID_PARAMETER", "FORBIDDEN_FIELD", "UNKNOWN_PARAMETER"} <= codes)

        out_of_range = GraphProposal(
            nodes=(
                GraphNodeProposal(
                    "shape",
                    "shape",
                    context="obj",
                    parameters={"steps": 0},
                ),
            )
        )
        self.assertIn("INVALID_PARAMETER", {item.code for item in self.compiler.validate(out_of_range)})

        invalid_mapping = {
            "nodes": [
                {
                    "node_id": "source",
                    "node_type": "source",
                    "context": "obj",
                    "parameters": {"density": float("inf")},
                }
            ],
            "command": "houdini -c unsafe",
        }
        mapping_codes = {item.code for item in self.compiler.validate(invalid_mapping)}
        self.assertIn("FORBIDDEN_FIELD", mapping_codes)
        self.assertIn(
            "INVALID_PARAMETER",
            {
                item.code
                for item in self.compiler.validate(
                    GraphProposal(
                        nodes=(
                            GraphNodeProposal(
                                "source",
                                "source",
                                context="obj",
                                parameters={"density": float("inf")},
                            ),
                        )
                    )
                )
            },
        )

    def test_multi_input_and_branch_connections_are_indexed(self) -> None:
        proposal = GraphProposal(
            nodes=(
                GraphNodeProposal("merge", "merge", context="obj"),
                GraphNodeProposal("right", "shape", context="obj"),
                GraphNodeProposal("source", "source", context="obj"),
                GraphNodeProposal("left", "shape", context="obj"),
            ),
            connections=(
                GraphConnection("right", "volume", "merge", "input", target_index=1),
                GraphConnection("source", "volume", "right", "source"),
                GraphConnection("left", "volume", "merge", "input", target_index=0),
                GraphConnection("source", "volume", "left", "source"),
            ),
            outputs=(GraphOutput("volume", "merge", "volume"),),
        )
        compiled = self.compiler.compile(proposal)
        self.assertEqual([item.target_index for item in compiled.connections if item.target_node == "obj:/merge"], [0, 1])
        self.assertEqual(compiled.execution_order[0], "obj:/source")
        self.assertEqual(compiled.execution_order[-1], "obj:/merge")

        single_input = GraphProposal(
            nodes=(
                GraphNodeProposal("one", "source", context="obj"),
                GraphNodeProposal("two", "source", context="obj"),
                GraphNodeProposal("shape", "shape", context="obj"),
            ),
            connections=(
                GraphConnection("one", "volume", "shape", "source"),
                GraphConnection("two", "volume", "shape", "source"),
            ),
        )
        self.assertIn("MULTIPLE_CONNECTIONS", {item.code for item in self.compiler.validate(single_input)})

    def test_multi_input_edges_without_indexes_are_rejected_as_ambiguous(self) -> None:
        proposal = GraphProposal(
            nodes=(
                GraphNodeProposal("left", "source", context="obj"),
                GraphNodeProposal("right", "source", context="obj"),
                GraphNodeProposal("merge", "merge", context="obj"),
            ),
            connections=(
                GraphConnection("left", "volume", "merge", "input"),
                GraphConnection("right", "volume", "merge", "input"),
            ),
        )
        diagnostics = self.compiler.validate(proposal)
        self.assertIn("AMBIGUOUS_INPUT_INDEX", {item.code for item in diagnostics})
        with self.assertRaises(GraphCompileError):
            self.compiler.compile(proposal)

    def test_node_ids_and_path_parameters_reject_ambiguous_whitespace_and_windows_paths(self) -> None:
        spaced = GraphProposal(nodes=(GraphNodeProposal(" source ", "source", context="obj"),))
        self.assertIn("INVALID_NODE_ID", {item.code for item in self.compiler.validate(spaced)})

        path_node = NodeSpec(
            "path_source",
            parameters=(ParameterSpec("texture", "path", required=True),),
            allowed_contexts=("obj",),
        )
        path_compiler = GraphCompiler(
            {"path_source": path_node},
            {"obj": GraphContext("obj", allowed_node_types=("path_source",))},
        )
        for value in ("C:/Windows/System32", "C:\\Windows\\System32", "\\\\server\\share\\file"):
            with self.subTest(value=value):
                diagnostics = path_compiler.validate(
                    GraphProposal(
                        nodes=(GraphNodeProposal("node", "path_source", context="obj", parameters={"texture": value}),)
                    )
                )
                self.assertIn("INVALID_PARAMETER", {item.code for item in diagnostics})

    def test_subnet_paths_and_boundaries_are_explicit(self) -> None:
        valid = GraphProposal(
            nodes=(
                GraphNodeProposal("source", "source", context="obj", subnet_path=("sim",)),
                GraphNodeProposal("display", "display", context="stage", subnet_path=("render",)),
            ),
            connections=(GraphConnection("obj:/sim/source", "volume", "stage:/render/display", "source"),),
        )
        compiled = self.compiler.compile(valid)
        self.assertTrue(compiled.connections[0].crosses_boundary)

        traversal = GraphProposal(
            nodes=(GraphNodeProposal("source", "source", context="obj", subnet_path=("..",)),)
        )
        self.assertIn("PATH_TRAVERSAL", {item.code for item in self.compiler.validate(traversal)})

        denied_boundary = GraphCompiler(_catalog(plain_display=True), _contexts()).validate(
            GraphProposal(
                nodes=(
                    GraphNodeProposal("source", "source", context="obj"),
                    GraphNodeProposal("display", "display", context="stage"),
                ),
                connections=(
                    GraphConnection("obj:/source", "volume", "stage:/display", "source"),
                ),
            )
        )
        self.assertIn("BOUNDARY_NOT_ALLOWLISTED", {item.code for item in denied_boundary})

    def test_unknown_reference_and_unknown_node_type_never_compile(self) -> None:
        proposal = GraphProposal(
            nodes=(
                GraphNodeProposal("source", "source", context="obj"),
                GraphNodeProposal("mystery", "not_in_catalog", context="obj"),
            ),
            connections=(GraphConnection("../../source", "volume", "mystery", "input"),),
        )
        codes = {item.code for item in self.compiler.validate(proposal)}
        self.assertIn("UNKNOWN_NODE_TYPE", codes)
        self.assertIn("PATH_TRAVERSAL", codes)

    def test_cycles_are_rejected_unless_a_catalog_boundary_allows_them(self) -> None:
        nodes = (
            GraphNodeProposal("a", "loop", context="obj"),
            GraphNodeProposal("b", "loop", context="obj"),
        )
        connections = (
            GraphConnection("a", "output", "b", "input"),
            GraphConnection("b", "output", "a", "input"),
        )
        rejected = GraphCompiler(_catalog(cycle_boundary=False), _contexts()).validate(
            GraphProposal(nodes=nodes, connections=connections)
        )
        self.assertIn("CYCLE_DETECTED", {item.code for item in rejected})

        allowed = GraphCompiler(_catalog(cycle_boundary=True), _contexts()).compile(
            GraphProposal(nodes=nodes, connections=connections)
        )
        self.assertEqual(allowed.cycle_boundaries, ("obj:/a", "obj:/b"))
        self.assertEqual(len(allowed.execution_order), 2)

    def test_mapping_parser_rejects_unknown_nested_fields_with_diagnostics(self) -> None:
        payload = {
            "nodes": [
                {
                    "node_id": "source",
                    "node_type": "source",
                    "context": "obj",
                    "script": "hou.node('/obj').destroy()",
                }
            ]
        }
        with self.assertRaises(GraphCompileError) as caught:
            GraphProposal.from_mapping(payload)
        diagnostics = caught.exception.diagnostics
        self.assertEqual(diagnostics[0].code, "FORBIDDEN_FIELD")
        self.assertEqual(diagnostics[0].path, "$.nodes[0]")

        wrong_version = self.compiler.validate({"schema_version": "9.0", "nodes": []})
        self.assertIn("SCHEMA_VERSION_UNSUPPORTED", {item.code for item in wrong_version})


if __name__ == "__main__":
    unittest.main()
