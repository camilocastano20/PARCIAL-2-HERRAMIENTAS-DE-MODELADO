"""Jerarquía de excepciones propia (Parte E-12)."""
from __future__ import annotations

from enum import Enum


class SurgiPlanError(Exception):
    """Raíz de todos los errores del dominio."""


class ConflictoProgramacionError(SurgiPlanError):
    """Choque de recursos al programar (RN1, RN3, RN6, RN9...)."""

    def __init__(self, regla: str, mensaje: str) -> None:
        super().__init__(f"[{regla}] {mensaje}")
        self.regla = regla
        self.mensaje = mensaje


class SinQuirofanoDisponibleError(ConflictoProgramacionError):
    """RN9: no hay quirófano libre ni cirugía electiva desplazable."""


class ConflictoVersionError(ConflictoProgramacionError):
    """Bloqueo optimista: el recurso cambió desde que se leyó (Parte G-17)."""


class GuardaIncumplidaError(SurgiPlanError):
    """Una guarda de transición o precondición de negocio no se cumple."""

    def __init__(self, regla: str, mensaje: str) -> None:
        super().__init__(f"[{regla}] {mensaje}")
        self.regla = regla
        self.mensaje = mensaje


class PermisoDenegadoError(GuardaIncumplidaError):
    """RN16: el actor no está autorizado para el evento."""

    def __init__(self, mensaje: str) -> None:
        super().__init__("RN16", mensaje)


class TransicionInvalidaError(SurgiPlanError):
    """No existe transición para (estado, evento) (RN10)."""

    def __init__(
        self,
        estado_origen: Enum | None,
        evento: str,
        mensaje: str | None = None,
        regla: str = "RN10",
    ) -> None:
        nombre = estado_origen.name if estado_origen is not None else "<inicial>"
        texto = mensaje or f"El evento '{evento}' no es válido desde el estado {nombre}."
        super().__init__(f"[{regla}] {texto}")
        self.estado_origen = estado_origen
        self.evento = evento
        self.regla = regla
        self.mensaje = texto


class FranjaInvalidaError(SurgiPlanError, ValueError):
    """Franja horaria mal formada (fin <= inicio, zonas horarias mezcladas)."""
