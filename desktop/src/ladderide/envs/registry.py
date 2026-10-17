"""Registro e descoberta dos ambientes de simulacao.

Ambientes sao descobertos automaticamente:
  * todos os modulos do pacote ladderide.envs.builtin;
  * arquivos .py em ~/.ladderide/ambientes/ (ambientes do usuario, sem
    precisar alterar a IDE).
Cada modulo registra suas classes com o decorador @register.
"""
from __future__ import annotations

import importlib
import importlib.util
import pkgutil
from pathlib import Path

from .base import Environment

_REGISTRY: dict[str, type[Environment]] = {}
_LOADED = False
load_errors: list[str] = []

USER_DIR = Path.home() / ".ladderide" / "ambientes"


def register(cls: type[Environment]) -> type[Environment]:
    if not cls.id:
        raise ValueError(f"{cls.__name__}: defina o atributo id")
    if cls.id in _REGISTRY and _REGISTRY[cls.id] is not cls:
        raise ValueError(f"ambiente '{cls.id}' registrado duas vezes")
    _REGISTRY[cls.id] = cls
    return cls


def discover(extra_dirs: list[Path] | None = None) -> None:
    global _LOADED
    if _LOADED and not extra_dirs:
        return
    from . import builtin
    for mod in pkgutil.iter_modules(builtin.__path__):
        importlib.import_module(f"{builtin.__name__}.{mod.name}")
    for folder in [USER_DIR, *(extra_dirs or [])]:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.py")):
            try:
                spec = importlib.util.spec_from_file_location(f"ladderide_env_{path.stem}", path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            except Exception as exc:  # noqa: BLE001 - um plugin com erro nao derruba a IDE
                load_errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
    _LOADED = True


def available() -> list[type[Environment]]:
    discover()
    return sorted(_REGISTRY.values(), key=lambda c: c.name)


def get(env_id: str) -> type[Environment] | None:
    discover()
    return _REGISTRY.get(env_id)


def create(env_id: str) -> Environment:
    cls = get(env_id)
    if cls is None:
        raise KeyError(f"ambiente desconhecido: {env_id}")
    return cls()
