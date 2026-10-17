"""Geracao de codigo-fonte a partir do diagrama LADDER."""
from .cpp import CppCode, generate_cpp

__all__ = ["CppCode", "generate_cpp"]
