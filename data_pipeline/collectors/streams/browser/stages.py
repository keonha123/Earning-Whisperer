"""Replaceable browser capabilities sharing one agent's session state."""

from dataclasses import dataclass
from types import ModuleType

from . import discovery, flow, human, learning, playback, registration, session


@dataclass(frozen=True)
class BrowserStages:
    session: ModuleType = session
    discovery: ModuleType = discovery
    registration: ModuleType = registration
    playback: ModuleType = playback
    learning: ModuleType = learning
    human: ModuleType = human
    flow: ModuleType = flow
