"""Shared policy contract for the backend and standalone visual pipeline."""
from ..core.v4_bridge import load

_contract = load("agent_experience")
VERSION = _contract.VERSION
ExperienceError = _contract.ExperienceError
digest = _contract.digest
normalize = _contract.normalize
match = _contract.match
conflicts = _contract.conflicts
freeze = _contract.freeze
