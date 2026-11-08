"""Extensiones de la Parte G-16 (sin modificar Cirugia ni Cirujano)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from .enums import RolEquipo
from .usuarios import PersonalClinico


class PuedeRegistrarNotas(Protocol):          # ISP: interfaz pequeña y específica
    def registrar_nota(self, cirugia_id: str, texto: str, momento: datetime) -> None: ...


@dataclass(frozen=True)
class NotaClinica:
    cirugia_id: str
    autor: str
    texto: str
    momento: datetime


class ResidenteCirugia(PersonalClinico, PuedeRegistrarNotas):
    """Hereda de PersonalClinico (NO de Cirujano): así no promete lo que Cirujano promete
    (poder ser principal / iniciar), y se respeta Liskov."""

    def __init__(self, identificacion: str, nombre: str, correo: str, activo: bool = True) -> None:
        super().__init__(identificacion, nombre, correo, activo)
        self.notas: list[NotaClinica] = []

    def rol_sistema(self) -> str:
        return "RESIDENTE"

    def roles_permitidos(self) -> frozenset[RolEquipo]:
        return frozenset({RolEquipo.OBSERVADOR})

    def registrar_nota(self, cirugia_id: str, texto: str, momento: datetime) -> None:
        self.notas.append(NotaClinica(cirugia_id, self.identificacion, texto, momento))


class ConsultaExistencias(Protocol):
    def existencias(self, codigo_insumo: str) -> int: ...


class RecepcionPedidos(Protocol):
    def recibir_pedido(self, codigo_insumo: str, cantidad: int) -> str: ...


@dataclass
class ProveedorInsumos(ConsultaExistencias, RecepcionPedidos):
    """Actor externo: NO es Usuario clínico; depende solo de dos interfaces (DIP/ISP)."""

    nombre: str
    inventario: dict[str, int] = field(default_factory=dict)
    pedidos: list[tuple[str, int]] = field(default_factory=list)

    def existencias(self, codigo_insumo: str) -> int:
        return self.inventario.get(codigo_insumo, 0)

    def recibir_pedido(self, codigo_insumo: str, cantidad: int) -> str:
        self.pedidos.append((codigo_insumo, cantidad))
        return f"PED-{len(self.pedidos):04d}"


def pedir_si_hace_falta(proveedor: ProveedorInsumos, codigo: str, minimo: int, cantidad: int) -> str | None:
    if proveedor.existencias(codigo) < minimo:
        return proveedor.recibir_pedido(codigo, cantidad)
    return None
