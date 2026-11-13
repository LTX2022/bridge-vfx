"""Deterministic metrics over caller-supplied numeric evidence."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .canonical import json_value
from .errors import RuntimeV2Error
from .models import ErrorCode


@dataclass(frozen=True)
class MetricProvenance:
    source_kind: str
    artifact_ids: tuple[str, ...]
    input_hashes: tuple[str, ...]
    method_version: str = "metric-engine-1.0"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_kind.strip() or not self.artifact_ids or not self.input_hashes:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "metric provenance requires source kind, artifact ids, and input hashes")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "artifact_ids": list(self.artifact_ids),
            "input_hashes": list(self.input_hashes),
            "method_version": self.method_version,
            "metadata": json_value(self.metadata),
        }


@dataclass(frozen=True)
class MetricResult:
    name: str
    value: float
    unit: str
    provenance: MetricProvenance
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not math.isfinite(self.value):
            raise RuntimeV2Error(ErrorCode.ARTIFACT_INVALID, "metric values must be finite")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value, "unit": self.unit, "provenance": self.provenance.to_dict(), "details": json_value(self.details)}


class MetricEngine:
    """No model inference and no hidden file decoding; equal inputs give equal outputs."""

    def raster_summary(self, raster: Sequence[Sequence[float]], provenance: MetricProvenance) -> tuple[MetricResult, ...]:
        matrix = self._matrix(raster, "raster")
        values = [value for row in matrix for value in row]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        differences = []
        for row_index, row in enumerate(matrix):
            for column_index, value in enumerate(row):
                if column_index + 1 < len(row):
                    differences.append(abs(value - row[column_index + 1]))
                if row_index + 1 < len(matrix):
                    differences.append(abs(value - matrix[row_index + 1][column_index]))
        edge_energy = sum(differences) / len(differences) if differences else 0.0
        details = {"height": len(matrix), "width": len(matrix[0])}
        return (
            MetricResult("raster.mean", mean, "value", provenance, details),
            MetricResult("raster.variance", variance, "value_squared", provenance, details),
            MetricResult("raster.edge_energy", edge_energy, "absolute_difference", provenance, details),
        )

    def compare_rasters(
        self,
        before: Sequence[Sequence[float]],
        after: Sequence[Sequence[float]],
        provenance: MetricProvenance,
    ) -> tuple[MetricResult, ...]:
        left = self._matrix(before, "before raster")
        right = self._matrix(after, "after raster")
        if len(left) != len(right) or len(left[0]) != len(right[0]):
            raise RuntimeV2Error(ErrorCode.ARTIFACT_INVALID, "raster comparison requires identical dimensions")
        differences = [right[row][column] - left[row][column] for row in range(len(left)) for column in range(len(left[0]))]
        mae = sum(abs(value) for value in differences) / len(differences)
        mse = sum(value * value for value in differences) / len(differences)
        before_edge = self.raster_summary(left, provenance)[2].value
        after_edge = self.raster_summary(right, provenance)[2].value
        ratio = after_edge / before_edge if before_edge else (1.0 if after_edge == 0.0 else after_edge)
        return (
            MetricResult("raster.mae", mae, "absolute_difference", provenance),
            MetricResult("raster.mse", mse, "difference_squared", provenance),
            MetricResult("raster.edge_energy_ratio", ratio, "ratio", provenance, {"before": before_edge, "after": after_edge}),
        )

    def sequence_summary(
        self,
        frames: Sequence[Sequence[Sequence[float]]],
        provenance: MetricProvenance,
    ) -> tuple[MetricResult, ...]:
        if not frames:
            raise RuntimeV2Error(ErrorCode.ARTIFACT_INVALID, "sequence must contain frames")
        normalized = [self._matrix(frame, "sequence frame") for frame in frames]
        shape = (len(normalized[0]), len(normalized[0][0]))
        if any((len(frame), len(frame[0])) != shape for frame in normalized):
            raise RuntimeV2Error(ErrorCode.ARTIFACT_INVALID, "sequence frames must have identical dimensions")
        temporal = []
        for previous, current in zip(normalized, normalized[1:]):
            temporal.extend(abs(current[row][column] - previous[row][column]) for row in range(shape[0]) for column in range(shape[1]))
        mean_delta = sum(temporal) / len(temporal) if temporal else 0.0
        coherence = 1.0 / (1.0 + mean_delta)
        active = sum(value > 0.0 for value in temporal) / len(temporal) if temporal else 0.0
        return (
            MetricResult("sequence.temporal_delta", mean_delta, "absolute_difference_per_frame", provenance, {"frames": len(normalized)}),
            MetricResult("sequence.temporal_coherence", coherence, "normalized", provenance, {"frames": len(normalized), "quality_score": False, "interpretation": "low pixel change also includes frozen footage"}),
            MetricResult("sequence.activity_fraction", active, "fraction", provenance, {"frames": len(normalized), "motion_observable": len(normalized) > 1}),
        )

    def scalar_field_summary(self, field_values: Sequence[Any], provenance: MetricProvenance) -> tuple[MetricResult, ...]:
        shape, flat = self._numeric_tensor(field_values)
        mean = sum(flat) / len(flat)
        variance = sum((value - mean) ** 2 for value in flat) / len(flat)
        return (
            MetricResult("field.mean", mean, "value", provenance, {"shape": list(shape)}),
            MetricResult("field.variance", variance, "value_squared", provenance, {"shape": list(shape)}),
        )

    def point_summary(self, points: Sequence[Sequence[float]], provenance: MetricProvenance) -> tuple[MetricResult, ...]:
        if not points:
            raise RuntimeV2Error(ErrorCode.ARTIFACT_INVALID, "point set must not be empty")
        dimensions = len(points[0])
        if dimensions < 2 or any(len(point) != dimensions for point in points):
            raise RuntimeV2Error(ErrorCode.ARTIFACT_INVALID, "points must have consistent dimensionality of at least two")
        normalized = [tuple(self._number(value, "point coordinate") for value in point) for point in points]
        centroid = tuple(sum(point[axis] for point in normalized) / len(normalized) for axis in range(dimensions))
        nearest = []
        if len(normalized) > 1:
            for index, point in enumerate(normalized):
                distances = [math.dist(point, other) for other_index, other in enumerate(normalized) if other_index != index]
                nearest.append(min(distances))
        nearest_mean = sum(nearest) / len(nearest) if nearest else 0.0
        nearest_variance = sum((value - nearest_mean) ** 2 for value in nearest) / len(nearest) if nearest else 0.0
        return (
            MetricResult("points.count", float(len(normalized)), "count", provenance, {"dimensions": dimensions}),
            MetricResult("points.nearest_neighbor_variance", nearest_variance, "distance_squared", provenance, {"centroid": list(centroid)}),
        )

    def geometry_summary(
        self,
        vertices: Sequence[Sequence[float]],
        faces: Sequence[Sequence[int]],
        provenance: MetricProvenance,
    ) -> tuple[MetricResult, ...]:
        if not vertices:
            raise RuntimeV2Error(ErrorCode.ARTIFACT_INVALID, "geometry must contain vertices")
        dimensions = len(vertices[0])
        normalized = [tuple(self._number(value, "vertex coordinate") for value in vertex) for vertex in vertices]
        if dimensions < 2 or any(len(vertex) != dimensions for vertex in normalized):
            raise RuntimeV2Error(ErrorCode.ARTIFACT_INVALID, "vertices must have consistent dimensionality")
        for face in faces:
            if len(face) < 3 or any(not isinstance(index, int) or index < 0 or index >= len(normalized) for index in face):
                raise RuntimeV2Error(ErrorCode.ARTIFACT_INVALID, "face indices are invalid")
        lower = [min(vertex[axis] for vertex in normalized) for axis in range(dimensions)]
        upper = [max(vertex[axis] for vertex in normalized) for axis in range(dimensions)]
        diagonal = math.dist(lower, upper)
        details = {"bounds_min": lower, "bounds_max": upper, "dimensions": dimensions}
        return (
            MetricResult("geometry.vertex_count", float(len(normalized)), "count", provenance, details),
            MetricResult("geometry.face_count", float(len(faces)), "count", provenance, details),
            MetricResult("geometry.bounds_diagonal", diagonal, "scene_units", provenance, details),
        )

    def decode_file(self, path: Path | str, provenance: MetricProvenance) -> tuple[MetricResult, ...]:
        raise RuntimeV2Error(
            ErrorCode.UNSUPPORTED_INPUT_DECODER,
            "the standard-library metric engine does not decode media or DCC files",
            {"path": str(path), "provenance": provenance.to_dict()},
        )

    @classmethod
    def _matrix(cls, values: Sequence[Sequence[float]], name: str) -> list[list[float]]:
        if not values or not values[0]:
            raise RuntimeV2Error(ErrorCode.ARTIFACT_INVALID, f"{name} must not be empty")
        width = len(values[0])
        if any(len(row) != width for row in values):
            raise RuntimeV2Error(ErrorCode.ARTIFACT_INVALID, f"{name} must be rectangular")
        return [[cls._number(value, name) for value in row] for row in values]

    @classmethod
    def _numeric_tensor(cls, value: Sequence[Any]) -> tuple[tuple[int, ...], list[float]]:
        if not isinstance(value, (list, tuple)) or not value:
            raise RuntimeV2Error(ErrorCode.ARTIFACT_INVALID, "numeric field must be a non-empty tensor")
        if isinstance(value[0], (list, tuple)):
            child_shapes = []
            flattened = []
            for child in value:
                shape, values = cls._numeric_tensor(child)
                child_shapes.append(shape)
                flattened.extend(values)
            if len(set(child_shapes)) != 1:
                raise RuntimeV2Error(ErrorCode.ARTIFACT_INVALID, "numeric field must be rectangular")
            return (len(value),) + child_shapes[0], flattened
        return (len(value),), [cls._number(item, "field value") for item in value]

    @staticmethod
    def _number(value: Any, name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise RuntimeV2Error(ErrorCode.ARTIFACT_INVALID, f"{name} must contain finite numeric values")
        return float(value)
