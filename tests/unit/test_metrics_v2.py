from __future__ import annotations

import unittest

from dcc_task_runtime import ErrorCode, MetricEngine, MetricProvenance, RuntimeV2Error


class MetricEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = MetricEngine()
        self.provenance = MetricProvenance("numeric_fixture", ("artifact",), ("input-hash",), metadata={"frame": 1})

    def test_raster_and_sequence_metrics_are_deterministic(self) -> None:
        raster = [[0.0, 1.0], [1.0, 0.0]]
        first = self.engine.raster_summary(raster, self.provenance)
        second = self.engine.raster_summary(raster, self.provenance)
        self.assertEqual(first, second)
        self.assertEqual(first[2].name, "raster.edge_energy")
        compared = self.engine.compare_rasters([[0.0, 0.0], [0.0, 0.0]], raster, self.provenance)
        self.assertGreater(compared[0].value, 0.0)
        sequence = self.engine.sequence_summary((raster, [[1.0, 1.0], [1.0, 1.0]]), self.provenance)
        self.assertGreaterEqual(sequence[1].value, 0.0)

    def test_frozen_sequence_reports_no_motion_despite_high_coherence(self):
        frozen = {item.name: item for item in self.engine.sequence_summary([[[0.0]], [[0.0]]], self.provenance)}
        moving = {item.name: item for item in self.engine.sequence_summary([[[0.0]], [[1.0]]], self.provenance)}
        self.assertEqual(frozen["sequence.activity_fraction"].value, 0)
        self.assertGreater(moving["sequence.activity_fraction"].value, 0)
        self.assertFalse(frozen["sequence.temporal_coherence"].details["quality_score"])
        one = {item.name: item for item in self.engine.sequence_summary([[[0.0]]], self.provenance)}
        self.assertFalse(one["sequence.activity_fraction"].details["motion_observable"])

    def test_field_particle_and_geometry_summaries_use_supplied_values(self) -> None:
        field = self.engine.scalar_field_summary([[[0.0, 1.0], [1.0, 2.0]], [[1.0, 2.0], [2.0, 3.0]]], self.provenance)
        self.assertEqual(field[0].details["shape"], [2, 2, 2])
        points = self.engine.point_summary(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (3.0, 0.0, 0.0)), self.provenance)
        self.assertEqual(points[0].value, 3.0)
        geometry = self.engine.geometry_summary(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), ((0, 1, 2),), self.provenance)
        self.assertEqual(geometry[1].value, 1.0)

    def test_invalid_numeric_data_and_file_decoding_are_explicit(self) -> None:
        with self.assertRaises(RuntimeV2Error):
            self.engine.raster_summary([[0.0], [0.0, 1.0]], self.provenance)
        with self.assertRaises(RuntimeV2Error) as decoder:
            self.engine.decode_file("/tmp/render.exr", self.provenance)
        self.assertEqual(decoder.exception.code, ErrorCode.UNSUPPORTED_INPUT_DECODER)


if __name__ == "__main__":
    unittest.main()
