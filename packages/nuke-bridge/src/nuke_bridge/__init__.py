"""Client and command registry for the local Nuke Bridge."""

from .client import NukeClient, NukeConnectionError, NukeInstance, discover_instances
from .registry import COMMANDS, canonical_command

__all__ = ("COMMANDS", "NukeClient", "NukeConnectionError", "NukeInstance", "canonical_command", "discover_instances")

