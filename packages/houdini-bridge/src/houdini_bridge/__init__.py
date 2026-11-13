"""Client and command registry for the local Houdini Bridge."""

from .client import BridgeError, HoudiniClient, HoudiniInstance, discover_instances
from .domain_packs import EffectDomainPack, all_domain_packs, get_domain_pack, pack_catalog
from .registry import COMMANDS, canonical_command

__all__ = (
    "BridgeError",
    "COMMANDS",
    "EffectDomainPack",
    "HoudiniClient",
    "HoudiniInstance",
    "all_domain_packs",
    "canonical_command",
    "discover_instances",
    "get_domain_pack",
    "pack_catalog",
)
