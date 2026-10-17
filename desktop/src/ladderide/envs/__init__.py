"""Ambientes de simulacao: processos fisicos animados controlados pelo programa LADDER.

Para criar um ambiente novo, veja docs/simulation-environments.md.
"""
from .base import BUTTON, SENSOR, SWITCH, Environment, EnvironmentPlant, IOPoint
from .registry import available, create, discover, get, register

__all__ = ["BUTTON", "SENSOR", "SWITCH", "Environment", "EnvironmentPlant", "IOPoint", "available", "create",
           "discover", "get", "register"]
