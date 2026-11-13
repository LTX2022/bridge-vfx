"""Strict reference-media and visual-objective contracts.

This module is a pure contract layer between a registered media manifest, an
external vision response, and a bounded source plan.  It intentionally does
not read media, call a model, or emit DCC code.  Values coming from a model
are kept separate from values inferred by the contract and from mechanical
defaults so that an incomplete analysis cannot silently become a recipe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from .canonical import canonical_sha256, json_value
from .errors import RuntimeV2Error
from .models import ErrorCode, validate_frame_range


MEDIA_MANIFEST_VERSION = "1.0"
REFERENCE_ANALYSIS_VERSION = "1.0"
VISUAL_OBJECTIVE_VERSION = "1.0"
SOURCE_PLAN_VERSION = "1.0"

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_MEDIA_KINDS = frozenset({"image", "sequence", "video", "mask", "depth", "plate"})
_PROVENANCES = frozenset({"observed", "inferred", "estimated", "default", "unknown"})
_SPEED_TIERS = frozenset({"slow", "medium", "fast", "very_fast"})
_UNTRUSTED_CLASSIFICATION_WORDS = frozenset(
    {
        "privacy",
        "privacyclass",
        "privacyclassification",
        "synthetic",
        "syntheticinput",
        "issynthetic",
        "inputclass",
        "dataclass",
        "dataclassification",
    }
)


def _error(code: ErrorCode, message: str, path: str = "$") -> RuntimeV2Error:
    return RuntimeV2Error(code, message, {"path": path})


def _strict_keys(value: Mapping[str, Any], allowed: Iterable[str], name: str, code: ErrorCode) -> None:
    unknown = sorted(str(key) for key in value if key not in set(allowed))
    if unknown:
        raise RuntimeV2Error(code, f"{name} contains unknown fields", {"path": name, "fields": unknown})


def _required_string(value: Any, name: str, code: ErrorCode = ErrorCode.INVALID_SPEC) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(code, f"{name} must be a non-empty string", name)
    rendered = value.strip()
    if "\n" in rendered or "\r" in rendered:
        raise _error(code, f"{name} must not contain line breaks", name)
    return rendered


def _identifier(value: Any, name: str, code: ErrorCode = ErrorCode.INVALID_SPEC) -> str:
    rendered = _required_string(value, name, code)
    if not _IDENTIFIER.fullmatch(rendered):
        raise _error(code, f"{name} must be a stable identifier", name)
    return rendered


def _finite_number(value: Any, name: str, code: ErrorCode = ErrorCode.INVALID_SPEC) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _error(code, f"{name} must be a finite number", name)
    rendered = float(value)
    if not math.isfinite(rendered):
        raise _error(code, f"{name} must be a finite number", name)
    return rendered


def _bounded_number(value: Any, name: str, minimum: float, maximum: float, code: ErrorCode) -> float:
    rendered = _finite_number(value, name, code)
    if rendered < minimum or rendered > maximum:
        raise RuntimeV2Error(code, f"{name} is outside its declared range", {"path": name, "minimum": minimum, "maximum": maximum, "actual": rendered})
    return rendered


def _json_safe(value: Any, name: str, code: ErrorCode) -> Any:
    try:
        return json_value(value)
    except (TypeError, ValueError) as exc:
        raise _error(code, f"{name} must contain finite JSON values", name) from exc


def _classification_key(value: Any) -> str:
    return "".join(character for character in str(value).casefold() if character.isalnum())


def _reject_untrusted_classification(value: Any, path: str = "$") -> None:
    """Reject model-supplied privacy/synthetic classification fields.

    A model response may describe visual content, but it cannot attest to the
    privacy class of the bytes that were supplied to it.  A registered media
    manifest remains the only input identity boundary; these fields are
    therefore rejected instead of copied into a trusted record.
    """

    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = _classification_key(key)
            if normalized in _UNTRUSTED_CLASSIFICATION_WORDS or "privacy" in normalized or "synthetic" in normalized:
                raise RuntimeV2Error(
                    ErrorCode.MODEL_CAPABILITY_MISMATCH,
                    "reference analysis may not self-attest privacy or synthetic input classification",
                    {"path": f"{path}.{key}"},
                )
            _reject_untrusted_classification(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_untrusted_classification(item, f"{path}[{index}]")


def _parse_frame_range(value: Any, name: str, code: ErrorCode) -> Tuple[int, int, int]:
    if isinstance(value, Mapping):
        _strict_keys(value, {"start", "end", "step"}, name, code)
        raw_start, raw_end, raw_step = value.get("start"), value.get("end"), value.get("step", 1)
    elif isinstance(value, (list, tuple)) and len(value) == 3:
        # Tuple/list is the canonical in-memory form emitted by
        # SemanticValue.to_dict(); mappings remain the accepted input form.
        raw_start, raw_end, raw_step = value
    else:
        raise _error(code, f"{name} must be an object or a three-item range", name)
    if isinstance(raw_start, bool) or not isinstance(raw_start, int):
        raise _error(code, f"{name}.start must be an integer", f"{name}.start")
    if isinstance(raw_end, bool) or not isinstance(raw_end, int):
        raise _error(code, f"{name}.end must be an integer", f"{name}.end")
    if isinstance(raw_step, bool) or not isinstance(raw_step, int):
        raise _error(code, f"{name}.step must be an integer", f"{name}.step")
    try:
        validate_frame_range(raw_start, raw_end, raw_step, name, max_count=100000)
    except ValueError as exc:
        raise _error(code, str(exc), name) from exc
    return raw_start, raw_end, raw_step


def _parse_roi(value: Any, name: str, code: ErrorCode) -> Tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise _error(code, f"{name} must contain four normalized values", name)
    result = tuple(_bounded_number(item, f"{name}[{index}]", 0.0, 1.0, code) for index, item in enumerate(value))
    return result  # type: ignore[return-value]


@dataclass(frozen=True)
class MediaAsset:
    """One registered media item; no model-provided privacy fields are allowed."""

    asset_id: str
    kind: str
    uri: str
    sha256: str
    frame_range: Optional[Tuple[int, int, int]] = None
    fps: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_id", _identifier(self.asset_id, "asset_id"))
        kind = getattr(self.kind, "value", self.kind)
        kind = _required_string(kind, "kind").casefold()
        if kind not in _MEDIA_KINDS:
            raise _error(ErrorCode.INVALID_SPEC, "media asset kind is unsupported", "kind")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "uri", _required_string(self.uri, "uri"))
        sha = _required_string(self.sha256, "sha256").lower()
        if not _SHA256.fullmatch(sha):
            raise _error(ErrorCode.INVALID_SPEC, "media asset sha256 must be 64 hexadecimal characters", "sha256")
        object.__setattr__(self, "sha256", sha)
        if self.frame_range is not None:
            object.__setattr__(self, "frame_range", _parse_frame_range(self.frame_range, "frame_range", ErrorCode.INVALID_SPEC))
        if self.fps is not None:
            object.__setattr__(self, "fps", _bounded_number(self.fps, "fps", 0.000001, 1000.0, ErrorCode.INVALID_SPEC))
        for name in ("width", "height"):
            value = getattr(self, name)
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > 1000000:
                    raise _error(ErrorCode.INVALID_SPEC, f"{name} must be a positive bounded integer", name)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MediaAsset":
        if not isinstance(value, Mapping):
            raise _error(ErrorCode.INVALID_SPEC, "media asset must be an object", "asset")
        _reject_untrusted_classification(value, "asset")
        _strict_keys(value, {"asset_id", "kind", "uri", "sha256", "frame_range", "fps", "width", "height"}, "asset", ErrorCode.INVALID_SPEC)
        frame_range = _parse_frame_range(value["frame_range"], "asset.frame_range", ErrorCode.INVALID_SPEC) if value.get("frame_range") is not None else None
        return cls(
            asset_id=value.get("asset_id"),
            kind=value.get("kind"),
            uri=value.get("uri"),
            sha256=value.get("sha256"),
            frame_range=frame_range,
            fps=value.get("fps"),
            width=value.get("width"),
            height=value.get("height"),
        )

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "asset_id": self.asset_id,
            "kind": self.kind,
            "uri": self.uri,
            "sha256": self.sha256,
        }
        if self.frame_range is not None:
            result["frame_range"] = {"start": self.frame_range[0], "end": self.frame_range[1], "step": self.frame_range[2]}
        if self.fps is not None:
            result["fps"] = self.fps
        if self.width is not None:
            result["width"] = self.width
        if self.height is not None:
            result["height"] = self.height
        return result


@dataclass(frozen=True)
class MediaManifest:
    """An immutable, ordered manifest of media registered outside the model."""

    assets: Tuple[MediaAsset, ...]
    schema_version: str = MEDIA_MANIFEST_VERSION
    manifest_sha256: Optional[str] = None

    def __post_init__(self) -> None:
        if self.schema_version != MEDIA_MANIFEST_VERSION:
            raise _error(ErrorCode.SCHEMA_VERSION_UNSUPPORTED, "media manifest schema_version is unsupported", "schema_version")
        assets = tuple(self.assets or ())
        if not assets or any(not isinstance(item, MediaAsset) for item in assets):
            raise _error(ErrorCode.INVALID_SPEC, "media manifest requires MediaAsset entries", "assets")
        identifiers = [item.asset_id for item in assets]
        if len(identifiers) != len(set(identifiers)):
            raise _error(ErrorCode.INVALID_SPEC, "media asset ids must be unique", "assets")
        object.__setattr__(self, "assets", assets)
        if self.manifest_sha256 is not None:
            supplied = _required_string(self.manifest_sha256, "manifest_sha256").lower()
            if not _SHA256.fullmatch(supplied):
                raise _error(ErrorCode.INVALID_SPEC, "manifest_sha256 must be 64 hexadecimal characters", "manifest_sha256")
            if supplied != self.content_sha256:
                raise RuntimeV2Error(
                    ErrorCode.INVALID_SPEC,
                    "manifest_sha256 does not match the ordered asset manifest",
                    {"path": "manifest_sha256", "actual": self.content_sha256},
                )
            object.__setattr__(self, "manifest_sha256", supplied)
        else:
            object.__setattr__(self, "manifest_sha256", self.content_sha256)

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(
            {
                "schema_version": self.schema_version,
                "assets": [item.to_dict() for item in self.assets],
            }
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MediaManifest":
        if not isinstance(value, Mapping):
            raise _error(ErrorCode.INVALID_SPEC, "media_manifest must be an object", "media_manifest")
        _reject_untrusted_classification(value, "media_manifest")
        _strict_keys(value, {"schema_version", "assets", "manifest_sha256"}, "media_manifest", ErrorCode.INVALID_SPEC)
        raw_assets = value.get("assets")
        if not isinstance(raw_assets, (list, tuple)):
            raise _error(ErrorCode.INVALID_SPEC, "media_manifest.assets must be an array", "media_manifest.assets")
        return cls(
            assets=tuple(MediaAsset.from_mapping(item) for item in raw_assets),
            schema_version=value.get("schema_version"),
            manifest_sha256=value.get("manifest_sha256"),
        )

    @classmethod
    def from_reference_assets(cls, references: Sequence[Any]) -> "MediaManifest":
        """Create a manifest from already registered ReferenceAsset-like values.

        Only identity fields are copied.  Arbitrary ``metadata`` on a legacy
        reference is deliberately ignored and cannot become trusted objective
        input.
        """

        assets: List[MediaAsset] = []
        for index, reference in enumerate(references):
            if isinstance(reference, Mapping):
                asset = MediaAsset.from_mapping(reference)
            else:
                kind = getattr(getattr(reference, "kind", None), "value", getattr(reference, "kind", None))
                asset = MediaAsset(
                    asset_id=getattr(reference, "asset_id", None),
                    kind=kind,
                    uri=getattr(reference, "uri", None),
                    sha256=getattr(reference, "sha256", None),
                    frame_range=getattr(reference, "frame_range", None),
                )
            assets.append(asset)
        if not assets:
            raise _error(ErrorCode.INVALID_SPEC, "at least one registered reference is required", "references")
        return cls(tuple(assets))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "assets": [item.to_dict() for item in self.assets],
            "manifest_sha256": self.content_sha256,
        }


@dataclass(frozen=True)
class AnalysisComponent:
    component_id: str
    label: str
    roi: Optional[Tuple[float, float, float, float]]
    observations: Mapping[str, Any]
    confidence: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "component_id", _required_string(self.component_id, "component.component_id", ErrorCode.MODEL_CAPABILITY_MISMATCH))
        object.__setattr__(self, "label", _required_string(self.label, "component.label", ErrorCode.MODEL_CAPABILITY_MISMATCH))
        if self.roi is not None:
            object.__setattr__(self, "roi", _parse_roi(self.roi, "component.roi", ErrorCode.MODEL_CAPABILITY_MISMATCH))
        if not isinstance(self.observations, Mapping):
            raise _error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "component.observations must be an object", "component.observations")
        _reject_untrusted_classification(self.observations, "component.observations")
        object.__setattr__(self, "observations", dict(_json_safe(self.observations, "component.observations", ErrorCode.MODEL_CAPABILITY_MISMATCH)))
        object.__setattr__(self, "confidence", _bounded_number(self.confidence, "component.confidence", 0.0, 1.0, ErrorCode.MODEL_CAPABILITY_MISMATCH))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AnalysisComponent":
        if not isinstance(value, Mapping):
            raise _error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "analysis component must be an object", "components")
        _reject_untrusted_classification(value, "component")
        _strict_keys(value, {"component_id", "label", "roi", "observations", "confidence"}, "component", ErrorCode.MODEL_CAPABILITY_MISMATCH)
        return cls(value.get("component_id"), value.get("label"), value.get("roi"), value.get("observations"), value.get("confidence"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component_id": self.component_id,
            "label": self.label,
            "roi": list(self.roi) if self.roi is not None else None,
            "observations": json_value(self.observations),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ReferenceAnalysis:
    """Validated external analysis with the exact public vision shape."""

    components: Tuple[AnalysisComponent, ...]
    global_observations: Mapping[str, Any]
    confidence: float
    schema_version: str = REFERENCE_ANALYSIS_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REFERENCE_ANALYSIS_VERSION:
            raise _error(ErrorCode.SCHEMA_VERSION_UNSUPPORTED, "reference analysis schema_version is unsupported", "schema_version")
        components = tuple(self.components or ())
        if any(not isinstance(item, AnalysisComponent) for item in components):
            raise _error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "analysis components must be typed entries", "components")
        identifiers = [item.component_id for item in components]
        if len(identifiers) != len(set(identifiers)):
            raise _error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "analysis component ids must be unique", "components")
        if not isinstance(self.global_observations, Mapping):
            raise _error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "global_observations must be an object", "global_observations")
        _reject_untrusted_classification(self.global_observations, "global_observations")
        object.__setattr__(self, "components", components)
        object.__setattr__(self, "global_observations", dict(_json_safe(self.global_observations, "global_observations", ErrorCode.MODEL_CAPABILITY_MISMATCH)))
        object.__setattr__(self, "confidence", _bounded_number(self.confidence, "confidence", 0.0, 1.0, ErrorCode.MODEL_CAPABILITY_MISMATCH))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ReferenceAnalysis":
        if not isinstance(value, Mapping):
            raise _error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "reference analysis must be an object")
        _reject_untrusted_classification(value)
        _strict_keys(value, {"components", "global_observations", "confidence"}, "reference_analysis", ErrorCode.MODEL_CAPABILITY_MISMATCH)
        raw_components = value.get("components")
        if not isinstance(raw_components, (list, tuple)):
            raise _error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "components must be an array", "components")
        return cls(
            components=tuple(AnalysisComponent.from_mapping(item) for item in raw_components),
            global_observations=value.get("global_observations"),
            confidence=value.get("confidence"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "components": [item.to_dict() for item in self.components],
            "global_observations": json_value(self.global_observations),
            "confidence": self.confidence,
        }


def validate_reference_analysis(value: Union[ReferenceAnalysis, Mapping[str, Any]]) -> ReferenceAnalysis:
    """Validate and type the external ``components/global_observations/confidence`` shape."""

    if isinstance(value, ReferenceAnalysis):
        return value
    return ReferenceAnalysis.from_mapping(value)


class SemanticProvenance(str, Enum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    ESTIMATED = "estimated"
    DEFAULT = "default"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SemanticValue:
    """A value with explicit provenance; ``default`` is never an observation."""

    value: Any = None
    provenance: Union[SemanticProvenance, str] = SemanticProvenance.UNKNOWN
    confidence: Optional[float] = None
    basis: str = ""

    def __post_init__(self) -> None:
        provenance = getattr(self.provenance, "value", self.provenance)
        provenance = _required_string(provenance, "provenance").casefold()
        if provenance not in _PROVENANCES:
            raise _error(ErrorCode.INVALID_SPEC, "semantic provenance is unsupported", "provenance")
        object.__setattr__(self, "provenance", SemanticProvenance(provenance))
        if provenance == SemanticProvenance.UNKNOWN.value:
            if self.value is not None:
                raise _error(ErrorCode.INVALID_SPEC, "unknown semantic values must use value=null", "value")
        else:
            if self.value is None:
                raise _error(ErrorCode.INVALID_SPEC, "known semantic values must not use value=null", "value")
            _json_safe(self.value, "value", ErrorCode.INVALID_SPEC)
        if self.confidence is not None:
            object.__setattr__(self, "confidence", _bounded_number(self.confidence, "confidence", 0.0, 1.0, ErrorCode.INVALID_SPEC))
        if provenance in {SemanticProvenance.OBSERVED.value, SemanticProvenance.INFERRED.value, SemanticProvenance.ESTIMATED.value}:
            if self.confidence is None:
                raise _error(ErrorCode.INVALID_SPEC, "observed/inferred/estimated values require confidence", "confidence")
            object.__setattr__(self, "basis", _required_string(self.basis, "basis"))
        elif provenance == SemanticProvenance.DEFAULT.value:
            object.__setattr__(self, "basis", str(self.basis or "contract-default"))
        else:
            object.__setattr__(self, "basis", str(self.basis or "unknown"))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SemanticValue":
        if not isinstance(value, Mapping):
            raise _error(ErrorCode.INVALID_SPEC, "semantic value must be an object")
        _strict_keys(value, {"value", "provenance", "confidence", "basis"}, "semantic_value", ErrorCode.INVALID_SPEC)
        if "provenance" not in value:
            raise _error(ErrorCode.INVALID_SPEC, "semantic value requires provenance", "provenance")
        return cls(value.get("value"), value.get("provenance"), value.get("confidence"), str(value.get("basis") or ""))

    @classmethod
    def unknown(cls, basis: str = "missing") -> "SemanticValue":
        return cls(None, SemanticProvenance.UNKNOWN, None, basis)

    @property
    def is_known(self) -> bool:
        return self.provenance is not SemanticProvenance.UNKNOWN

    @property
    def is_observation(self) -> bool:
        return self.provenance is SemanticProvenance.OBSERVED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": json_value(self.value),
            "provenance": self.provenance.value,
            "confidence": self.confidence,
            "basis": self.basis,
        }


_SMOKE_FIELDS = (
    "emission_start",
    "emission_end",
    "direction",
    "spread_angle",
    "speed_tier",
    "body_scale",
    "ground_spread",
    "protected_features",
    "roi",
    "time_range",
)
_OBSERVATION_ALIASES: Mapping[str, Tuple[str, ...]] = {
    "emission_start": ("emission_start", "emission_start_frame", "emission_onset_frame"),
    "emission_end": ("emission_end", "emission_end_frame", "emission_stop_frame"),
    "direction": ("direction", "emission_direction", "flow_direction"),
    "spread_angle": ("spread_angle", "spread_angle_deg", "expansion_angle"),
    "speed_tier": ("speed_tier", "speed_class", "velocity_tier"),
    "body_scale": ("body_scale", "subject_scale", "plume_scale"),
    "ground_spread": ("ground_spread", "ground_expansion", "base_spread"),
    "protected_features": ("protected_features", "preserve_features"),
    "roi": ("roi", "region_of_interest"),
    "time_range": ("time_range", "frame_range"),
}


def _semantic_from_raw(value: Any, confidence: float, basis: str) -> SemanticValue:
    if isinstance(value, Mapping) and ("value" in value or "provenance" in value or "confidence" in value or "basis" in value):
        _strict_keys(value, {"value", "provenance", "confidence", "basis"}, basis, ErrorCode.MODEL_CAPABILITY_MISMATCH)
        raw_provenance = value.get("provenance")
        provenance = getattr(raw_provenance, "value", raw_provenance)
        provenance = str(provenance or "").casefold()
        if provenance == "unknown":
            return SemanticValue.unknown(basis)
        return SemanticValue(
            value=value.get("value"),
            provenance=provenance,
            confidence=value.get("confidence", confidence),
            basis=str(value.get("basis") or basis),
        )
    return SemanticValue(value=value, provenance=SemanticProvenance.OBSERVED, confidence=confidence, basis=basis)


def _normalise_field_value(field_name: str, value: Any, code: ErrorCode) -> Any:
    if field_name in {"emission_start", "emission_end"}:
        if isinstance(value, Mapping):
            _strict_keys(value, {"frame"}, field_name, code)
            value = value.get("frame")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 100000:
            raise _error(code, f"{field_name} must be an integer frame in range 0..100000", field_name)
        return value
    if field_name == "direction":
        if isinstance(value, Mapping):
            _strict_keys(value, {"x", "y", "z"}, field_name, code)
            if set(value) != {"x", "y", "z"}:
                raise _error(code, "direction requires x, y, and z", field_name)
            value = [value["x"], value["y"], value["z"]]
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise _error(code, "direction must contain three bounded components", field_name)
        vector = tuple(_bounded_number(item, f"{field_name}[{index}]", -1.0, 1.0, code) for index, item in enumerate(value))
        if math.sqrt(sum(item * item for item in vector)) <= 1.0e-9:
            raise _error(code, "direction must not be the zero vector", field_name)
        return vector
    if field_name == "spread_angle":
        if isinstance(value, Mapping):
            _strict_keys(value, {"degrees"}, field_name, code)
            value = value.get("degrees")
        return _bounded_number(value, field_name, 0.0, 180.0, code)
    if field_name == "speed_tier":
        value = getattr(value, "value", value)
        value = _required_string(value, field_name, code).casefold()
        if value not in _SPEED_TIERS:
            raise _error(code, "speed_tier must be slow, medium, fast, or very_fast", field_name)
        return value
    if field_name == "body_scale":
        if isinstance(value, Mapping):
            _strict_keys(value, {"relative"}, field_name, code)
            value = value.get("relative")
        return _bounded_number(value, field_name, 0.01, 100.0, code)
    if field_name == "ground_spread":
        if isinstance(value, Mapping):
            _strict_keys(value, {"relative"}, field_name, code)
            value = value.get("relative")
        return _bounded_number(value, field_name, 0.0, 100.0, code)
    if field_name == "protected_features":
        if isinstance(value, Mapping):
            _strict_keys(value, {"names"}, field_name, code)
            value = value.get("names")
        if not isinstance(value, (list, tuple)) or len(value) > 32:
            raise _error(code, "protected_features must contain at most 32 names", field_name)
        names = tuple(_required_string(item, f"{field_name}[{index}]", code) for index, item in enumerate(value))
        if len(set(names)) != len(names):
            raise _error(code, "protected_features must not contain duplicates", field_name)
        return names
    if field_name == "roi":
        return _parse_roi(value, field_name, code)
    if field_name == "time_range":
        start, end, step = _parse_frame_range(value, field_name, code)
        return {"start": start, "end": end, "step": step}
    raise _error(ErrorCode.INVALID_SPEC, "unregistered visual semantic", field_name)


def _normalise_semantic(field_name: str, semantic: SemanticValue) -> SemanticValue:
    if not isinstance(semantic, SemanticValue):
        raise _error(ErrorCode.INVALID_SPEC, f"{field_name} must be a typed SemanticValue", field_name)
    if not semantic.is_known:
        return semantic
    normalized = _normalise_field_value(field_name, semantic.value, ErrorCode.INVALID_SPEC)
    return SemanticValue(normalized, semantic.provenance, semantic.confidence, semantic.basis)


@dataclass(frozen=True)
class BoundedControl:
    """A source-plan value from a finite, registered control vocabulary."""

    name: str
    value: Any
    value_type: str
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    provenance: Union[SemanticProvenance, str] = SemanticProvenance.DEFAULT
    basis: str = "contract-default"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _identifier(self.name, "control.name"))
        value_type = _required_string(self.value_type, "control.value_type").casefold()
        if value_type not in {"int", "float", "enum", "vector3", "vector4", "frame_range", "string_list"}:
            raise _error(ErrorCode.INVALID_SPEC, "control.value_type is unsupported", "control.value_type")
        object.__setattr__(self, "value_type", value_type)
        if self.minimum is not None:
            object.__setattr__(self, "minimum", _finite_number(self.minimum, "control.minimum"))
        if self.maximum is not None:
            object.__setattr__(self, "maximum", _finite_number(self.maximum, "control.maximum"))
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise _error(ErrorCode.INVALID_SPEC, "control minimum cannot exceed maximum", "control")
        provenance = getattr(self.provenance, "value", self.provenance)
        provenance = _required_string(provenance, "control.provenance").casefold()
        if provenance not in _PROVENANCES:
            raise _error(ErrorCode.INVALID_SPEC, "control provenance is unsupported", "control.provenance")
        object.__setattr__(self, "provenance", SemanticProvenance(provenance))
        object.__setattr__(self, "basis", str(self.basis or "unknown"))
        _json_safe(self.value, "control.value", ErrorCode.INVALID_SPEC)
        if value_type == "int":
            if isinstance(self.value, bool) or not isinstance(self.value, int):
                raise _error(ErrorCode.INVALID_SPEC, "int control values must be integers", "control.value")
        elif value_type == "float":
            _finite_number(self.value, "control.value")
        elif value_type == "enum":
            _required_string(self.value, "control.value")
        elif value_type in {"vector3", "vector4"}:
            expected = 3 if value_type == "vector3" else 4
            if not isinstance(self.value, (list, tuple)) or len(self.value) != expected:
                raise _error(ErrorCode.INVALID_SPEC, f"{value_type} control must have {expected} components", "control.value")
            for index, item in enumerate(self.value):
                _finite_number(item, f"control.value[{index}]")
        elif value_type == "frame_range":
            _parse_frame_range(self.value, "control.value", ErrorCode.INVALID_SPEC)
        elif value_type == "string_list":
            if not isinstance(self.value, (list, tuple)) or any(not isinstance(item, str) or not item.strip() for item in self.value):
                raise _error(ErrorCode.INVALID_SPEC, "string_list control must contain non-empty strings", "control.value")
        if self.minimum is not None and self.maximum is not None:
            if value_type in {"int", "float"} and isinstance(self.value, (int, float)) and not isinstance(self.value, bool):
                if float(self.value) < self.minimum or float(self.value) > self.maximum:
                    raise _error(ErrorCode.INVALID_SPEC, "control value is outside its declared range", "control.value")
            elif value_type in {"vector3", "vector4"} and any(float(item) < self.minimum or float(item) > self.maximum for item in self.value):
                raise _error(ErrorCode.INVALID_SPEC, "control vector is outside its declared range", "control.value")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "BoundedControl":
        if not isinstance(value, Mapping):
            raise _error(ErrorCode.INVALID_SPEC, "source plan control must be an object", "controls")
        _strict_keys(
            value,
            {"name", "value", "value_type", "minimum", "maximum", "provenance", "basis"},
            "source plan control",
            ErrorCode.INVALID_SPEC,
        )
        return cls(
            name=value.get("name"),
            value=value.get("value"),
            value_type=value.get("value_type"),
            minimum=value.get("minimum"),
            maximum=value.get("maximum"),
            provenance=value.get("provenance", SemanticProvenance.DEFAULT.value),
            basis=value.get("basis", "contract-default"),
        )

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "name": self.name,
            "value": json_value(self.value),
            "value_type": self.value_type,
            "provenance": self.provenance.value,
            "basis": self.basis,
        }
        if self.minimum is not None:
            result["minimum"] = self.minimum
        if self.maximum is not None:
            result["maximum"] = self.maximum
        return result


@dataclass(frozen=True)
class SourcePlan:
    """Bounded, DCC-neutral source controls ready for a later executor."""

    recipe_id: str
    objective_hash: str
    media_manifest_sha256: str
    ready: bool
    controls: Tuple[BoundedControl, ...]
    defaults: Tuple[BoundedControl, ...]
    missing_semantics: Tuple[str, ...] = ()
    schema_version: str = SOURCE_PLAN_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SOURCE_PLAN_VERSION:
            raise _error(ErrorCode.SCHEMA_VERSION_UNSUPPORTED, "source plan schema_version is unsupported", "schema_version")
        object.__setattr__(self, "recipe_id", _identifier(self.recipe_id, "recipe_id"))
        for name in ("objective_hash", "media_manifest_sha256"):
            value = _required_string(getattr(self, name), name)
            if not _SHA256.fullmatch(value):
                raise _error(ErrorCode.INVALID_SPEC, f"{name} must be a SHA-256 hash", name)
            object.__setattr__(self, name, value.lower())
        controls = tuple(self.controls or ())
        defaults = tuple(self.defaults or ())
        if any(not isinstance(item, BoundedControl) for item in controls + defaults):
            raise _error(ErrorCode.INVALID_SPEC, "source plan controls must be typed entries", "controls")
        names = [item.name for item in controls + defaults]
        if len(names) != len(set(names)):
            raise _error(ErrorCode.INVALID_SPEC, "source plan control names must be unique", "controls")
        registered = {
            "emission_start_frame",
            "emission_end_frame",
            "direction",
            "spread_angle_deg",
            "speed_tier",
            "body_scale",
            "ground_spread",
            "protected_features",
            "roi",
            "time_range",
            "estimated_speed_magnitude",
            "pulse_count",
            "source_radius",
            "density",
            "dissipation",
            "voxel_size",
        }
        unknown_controls = sorted(set(names) - registered)
        if unknown_controls:
            raise RuntimeV2Error(
                ErrorCode.INVALID_SPEC,
                "source plan contains an unregistered control",
                {"path": "controls", "fields": unknown_controls},
            )
        missing = tuple(str(item) for item in self.missing_semantics)
        if any(item not in _SMOKE_FIELDS for item in missing) or len(set(missing)) != len(missing):
            raise _error(ErrorCode.INVALID_SPEC, "source plan missing_semantics is invalid", "missing_semantics")
        if bool(self.ready) != (not missing):
            raise _error(ErrorCode.INVALID_SPEC, "source plan ready must match missing_semantics", "ready")
        object.__setattr__(self, "controls", tuple(sorted(controls, key=lambda item: item.name)))
        object.__setattr__(self, "defaults", tuple(sorted(defaults, key=lambda item: item.name)))
        object.__setattr__(self, "missing_semantics", missing)
        object.__setattr__(self, "ready", bool(self.ready))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SourcePlan":
        if not isinstance(value, Mapping):
            raise _error(ErrorCode.INVALID_SPEC, "source plan must be an object", "source_plan")
        _strict_keys(
            value,
            {"schema_version", "recipe_id", "objective_hash", "media_manifest_sha256", "ready", "controls", "defaults", "missing_semantics"},
            "source plan",
            ErrorCode.INVALID_SPEC,
        )
        controls = value.get("controls", ())
        defaults = value.get("defaults", ())
        missing = value.get("missing_semantics", ())
        if not isinstance(controls, (list, tuple)) or not isinstance(defaults, (list, tuple)) or not isinstance(missing, (list, tuple)):
            raise _error(ErrorCode.INVALID_SPEC, "source plan list fields must be arrays", "source_plan")
        if type(value.get("ready")) is not bool:
            raise _error(ErrorCode.INVALID_SPEC, "source plan ready must be boolean", "ready")
        return cls(
            schema_version=value.get("schema_version", SOURCE_PLAN_VERSION),
            recipe_id=value.get("recipe_id"),
            objective_hash=value.get("objective_hash"),
            media_manifest_sha256=value.get("media_manifest_sha256"),
            ready=value.get("ready"),
            controls=tuple(BoundedControl.from_mapping(item) for item in controls),
            defaults=tuple(BoundedControl.from_mapping(item) for item in defaults),
            missing_semantics=tuple(str(item) for item in missing),
        )

    def require_ready(self) -> "SourcePlan":
        if not self.ready:
            raise RuntimeV2Error(
                ErrorCode.AWAITING_INPUT,
                "visual objective is incomplete; source plan cannot be executed",
                {"missing_semantics": list(self.missing_semantics)},
            )
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "recipe_id": self.recipe_id,
            "objective_hash": self.objective_hash,
            "media_manifest_sha256": self.media_manifest_sha256,
            "ready": self.ready,
            "controls": [item.to_dict() for item in self.controls],
            "defaults": [item.to_dict() for item in self.defaults],
            "missing_semantics": list(self.missing_semantics),
        }


@dataclass(frozen=True)
class VisualObjective:
    """Typed smoke visual target with explicit observation provenance."""

    media_manifest: MediaManifest
    emission_start: SemanticValue
    emission_end: SemanticValue
    direction: SemanticValue
    spread_angle: SemanticValue
    speed_tier: SemanticValue
    body_scale: SemanticValue
    ground_spread: SemanticValue
    protected_features: SemanticValue
    roi: SemanticValue
    time_range: SemanticValue
    schema_version: str = VISUAL_OBJECTIVE_VERSION
    objective_type: str = "smoke"

    def __post_init__(self) -> None:
        manifest = self.media_manifest
        if not isinstance(manifest, MediaManifest):
            if isinstance(manifest, Mapping):
                manifest = MediaManifest.from_mapping(manifest)
            else:
                raise _error(ErrorCode.INVALID_SPEC, "media_manifest must be a MediaManifest", "media_manifest")
        object.__setattr__(self, "media_manifest", manifest)
        if self.schema_version != VISUAL_OBJECTIVE_VERSION:
            raise _error(ErrorCode.SCHEMA_VERSION_UNSUPPORTED, "visual objective schema_version is unsupported", "schema_version")
        objective_type = _required_string(self.objective_type, "objective_type").casefold()
        if objective_type != "smoke":
            raise _error(ErrorCode.UNSUPPORTED_DOMAIN, "only the registered smoke objective is available", "objective_type")
        object.__setattr__(self, "objective_type", objective_type)
        for field_name in _SMOKE_FIELDS:
            object.__setattr__(self, field_name, _normalise_semantic(field_name, getattr(self, field_name)))
        if self.emission_start.is_known and self.emission_end.is_known and self.emission_end.value < self.emission_start.value:
            raise _error(ErrorCode.INVALID_SPEC, "emission_end must not precede emission_start", "emission_end")
        if self.time_range.is_known:
            start = self.time_range.value["start"]
            end = self.time_range.value["end"]
            if self.emission_start.is_known and not start <= self.emission_start.value <= end:
                raise _error(ErrorCode.INVALID_SPEC, "emission_start must lie inside time_range", "emission_start")
            if self.emission_end.is_known and not start <= self.emission_end.value <= end:
                raise _error(ErrorCode.INVALID_SPEC, "emission_end must lie inside time_range", "emission_end")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "VisualObjective":
        if not isinstance(value, Mapping):
            raise _error(ErrorCode.INVALID_SPEC, "visual objective must be an object")
        _strict_keys(value, set(_SMOKE_FIELDS) | {"schema_version", "objective_type", "media_manifest"}, "visual_objective", ErrorCode.INVALID_SPEC)
        required = set(_SMOKE_FIELDS) | {"schema_version", "objective_type", "media_manifest"}
        missing = sorted(item for item in required if item not in value)
        if missing:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "visual objective is missing required fields", {"fields": missing})
        semantics = {name: SemanticValue.from_mapping(value[name]) for name in _SMOKE_FIELDS}
        return cls(media_manifest=MediaManifest.from_mapping(value["media_manifest"]), schema_version=value["schema_version"], objective_type=value["objective_type"], **semantics)

    @classmethod
    def from_reference_analysis(
        cls,
        media_manifest: Union[MediaManifest, Mapping[str, Any]],
        analysis: Union[ReferenceAnalysis, Mapping[str, Any]],
    ) -> "VisualObjective":
        """Build only from registered structured observations.

        Free-form intent/feedback is intentionally absent from this method.
        An old analysis with no registered smoke fields returns explicit
        ``unknown`` values and therefore a non-ready source plan.
        """

        manifest = media_manifest if isinstance(media_manifest, MediaManifest) else MediaManifest.from_mapping(media_manifest)
        typed_analysis = analysis if isinstance(analysis, ReferenceAnalysis) else validate_reference_analysis(analysis)
        component = cls._smoke_component(typed_analysis.components)
        component_observations = dict(component.observations) if component is not None else {}
        global_observations = dict(typed_analysis.global_observations)
        confidence = min(typed_analysis.confidence, component.confidence) if component is not None else typed_analysis.confidence

        def select(field_name: str) -> SemanticValue:
            for source_name, observations in (("component", component_observations), ("global", global_observations)):
                for alias in _OBSERVATION_ALIASES[field_name]:
                    if alias in observations:
                        basis = f"{source_name}.observations.{alias}"
                        semantic = _semantic_from_raw(observations[alias], confidence, basis)
                        if not semantic.is_known:
                            return semantic
                        normalized = _normalise_field_value(field_name, semantic.value, ErrorCode.MODEL_CAPABILITY_MISMATCH)
                        return SemanticValue(normalized, semantic.provenance, semantic.confidence, semantic.basis)
            return SemanticValue.unknown(f"analysis.missing.{field_name}")

        roi = SemanticValue.unknown("analysis.missing.roi")
        if component is not None and component.roi is not None:
            roi = SemanticValue(component.roi, SemanticProvenance.OBSERVED, component.confidence, "component.roi")
        elif "roi" in global_observations:
            roi = select("roi")
        return cls(
            media_manifest=manifest,
            emission_start=select("emission_start"),
            emission_end=select("emission_end"),
            direction=select("direction"),
            spread_angle=select("spread_angle"),
            speed_tier=select("speed_tier"),
            body_scale=select("body_scale"),
            ground_spread=select("ground_spread"),
            protected_features=select("protected_features"),
            roi=roi,
            time_range=select("time_range"),
        )

    @classmethod
    def from_analysis(
        cls,
        analysis: Union[ReferenceAnalysis, Mapping[str, Any]],
        media_manifest: Union[MediaManifest, Mapping[str, Any]],
    ) -> "VisualObjective":
        """Argument-order alias convenient for gateway callers."""

        return cls.from_reference_analysis(media_manifest, analysis)

    @staticmethod
    def _smoke_component(components: Sequence[AnalysisComponent]) -> Optional[AnalysisComponent]:
        matches = []
        for component in components:
            label = component.label.casefold()
            identifier = component.component_id.casefold()
            label_tokens = set(re.findall(r"[a-z0-9]+", label))
            if ({"smoke", "dust"} & label_tokens) or identifier in {"smoke", "pyro_smoke", "dust"}:
                matches.append(component)
        if len(matches) == 1:
            return matches[0]
        return None

    @property
    def missing_semantics(self) -> Tuple[str, ...]:
        return tuple(name for name in _SMOKE_FIELDS if not getattr(self, name).is_known)

    @property
    def is_sufficient(self) -> bool:
        return not self.missing_semantics

    @property
    def objective_hash(self) -> str:
        return canonical_sha256(self.to_dict())

    def source_plan(self) -> SourcePlan:
        """Return a bounded plan; incomplete observations remain non-executable."""

        controls: List[BoundedControl] = []
        mapping = (
            ("emission_start", "emission_start_frame", "int", 0.0, 100000.0),
            ("emission_end", "emission_end_frame", "int", 0.0, 100000.0),
            ("direction", "direction", "vector3", -1.0, 1.0),
            ("spread_angle", "spread_angle_deg", "float", 0.0, 180.0),
            ("speed_tier", "speed_tier", "enum", None, None),
            ("body_scale", "body_scale", "float", 0.01, 100.0),
            ("ground_spread", "ground_spread", "float", 0.0, 100.0),
            ("protected_features", "protected_features", "string_list", None, None),
            ("roi", "roi", "vector4", 0.0, 1.0),
            ("time_range", "time_range", "frame_range", None, None),
        )
        for field_name, control_name, value_type, minimum, maximum in mapping:
            semantic = getattr(self, field_name)
            if semantic.is_known:
                controls.append(BoundedControl(control_name, semantic.value, value_type, minimum, maximum, semantic.provenance, semantic.basis))

        if self.speed_tier.is_known:
            speed_estimates = {"slow": 1.0, "medium": 2.5, "fast": 5.0, "very_fast": 8.0}
            controls.append(BoundedControl("estimated_speed_magnitude", speed_estimates[self.speed_tier.value], "float", 0.1, 20.0, SemanticProvenance.ESTIMATED, "speed_tier"))

        # These are mechanical recipe defaults, never observations extracted
        # from the reference.  They remain separate in the serialized plan.
        defaults = (
            BoundedControl("pulse_count", 1, "int", 1.0, 3.0, SemanticProvenance.DEFAULT, "contract-default"),
            BoundedControl("source_radius", 1.0, "float", 0.01, 10.0, SemanticProvenance.DEFAULT, "contract-default"),
            BoundedControl("density", 1.0, "float", 0.0, 10.0, SemanticProvenance.DEFAULT, "contract-default"),
            BoundedControl("dissipation", 0.25, "float", 0.0, 5.0, SemanticProvenance.DEFAULT, "contract-default"),
            BoundedControl("voxel_size", 0.1, "float", 0.005, 1.0, SemanticProvenance.DEFAULT, "contract-default"),
        )
        return SourcePlan(
            recipe_id="pyro_smoke_burst_v1",
            objective_hash=self.objective_hash,
            media_manifest_sha256=self.media_manifest.content_sha256,
            ready=self.is_sufficient,
            controls=tuple(controls),
            defaults=defaults,
            missing_semantics=self.missing_semantics,
        )

    def to_source_plan(self) -> SourcePlan:
        return self.source_plan()

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "schema_version": self.schema_version,
            "objective_type": self.objective_type,
            "media_manifest": self.media_manifest.to_dict(),
        }
        result.update({name: getattr(self, name).to_dict() for name in _SMOKE_FIELDS})
        return result


def build_source_plan(objective: VisualObjective) -> SourcePlan:
    """Typed convenience wrapper for callers that keep the objective opaque."""

    if not isinstance(objective, VisualObjective):
        raise _error(ErrorCode.INVALID_SPEC, "build_source_plan requires a VisualObjective", "objective")
    return objective.source_plan()


__all__ = (
    "AnalysisComponent",
    "BoundedControl",
    "MediaAsset",
    "MediaManifest",
    "ReferenceAnalysis",
    "SemanticProvenance",
    "SemanticValue",
    "SourcePlan",
    "VisualObjective",
    "build_source_plan",
    "validate_reference_analysis",
    "MEDIA_MANIFEST_VERSION",
    "REFERENCE_ANALYSIS_VERSION",
    "SOURCE_PLAN_VERSION",
    "VISUAL_OBJECTIVE_VERSION",
)


def parse_visual_objective(value):
    """Dispatch new domain objectives while retaining the original smoke schema."""
    from .domain_objective import DomainVisualObjective, DOMAIN_OBJECTIVE_SCHEMA
    if isinstance(value, Mapping) and value.get("schema_version") == DOMAIN_OBJECTIVE_SCHEMA:
        return DomainVisualObjective.from_mapping(value)
    return VisualObjective.from_mapping(value)
