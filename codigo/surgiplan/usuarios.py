"""Jerarquía de usuarios (Parte B-a): Usuario -> PersonalClinico -> Cirujano/Anestesiologo/Enfermero."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import TYPE_CHECKING, Collection

from .enums import TOPE_DIARIO_MINUTOS, Especialidad, RolEquipo
from .valores import FranjaHoraria, Habilitacion

if TYPE_CHECKING:
    from .cirugia import AsignacionProfesional, Cirugia


class Usuario(ABC):
    def __init__(self, identificacion: str, nombre: str, correo: str, activo: bool = True) -> None:
        self.identificacion = identificacion
        self.nombre = nombre
        self.correo = correo
        self.activo = activo

    @abstractmethod
    def rol_sistema(self) -> str: ...


class Coordinador(Usuario):
    def rol_sistema(self) -> str:
        return "COORDINADOR"


class Auditor(Usuario):
    """Solo lectura (RN16): ninguna transición lo autoriza."""

    def rol_sistema(self) -> str:
        return "AUDITOR"


class PersonalClinico(Usuario, ABC):
    def __init__(self, identificacion: str, nombre: str, correo: str, activo: bool = True) -> None:
        super().__init__(identificacion, nombre, correo, activo)
        self.asignaciones: list[AsignacionProfesional] = []

    @abstractmethod
    def roles_permitidos(self) -> frozenset[RolEquipo]: ...

    def asignaciones_vigentes(self, ignorando: Collection[Cirugia] = ()) -> list[AsignacionProfesional]:
        return [
            a for a in self.asignaciones if a.cirugia.es_vigente() and a.cirugia not in ignorando
        ]

    def minutos_en_dia(self, dia: date, ignorando: Collection[Cirugia] = ()) -> int:
        return sum(a.cirugia.franja.minutos_en_dia(dia) for a in self.asignaciones_vigentes(ignorando))

    def tiene_solapamiento(self, franja: FranjaHoraria, ignorando: Collection[Cirugia] = ()) -> bool:
        return any(a.cirugia.franja.solapa_con(franja) for a in self.asignaciones_vigentes(ignorando))

    def excede_tope_diario(self, franja: FranjaHoraria, ignorando: Collection[Cirugia] = ()) -> bool:
        """RN3: experto en información sobre sus propias asignaciones."""
        return any(
            self.minutos_en_dia(d, ignorando) + franja.minutos_en_dia(d) > TOPE_DIARIO_MINUTOS
            for d in franja.dias()
        )


class Cirujano(PersonalClinico):
    def __init__(self, identificacion: str, nombre: str, correo: str, activo: bool = True) -> None:
        super().__init__(identificacion, nombre, correo, activo)
        self.habilitaciones: list[Habilitacion] = []

    def rol_sistema(self) -> str:
        return "CIRUJANO"

    def roles_permitidos(self) -> frozenset[RolEquipo]:
        return frozenset({RolEquipo.CIRUJANO_PRINCIPAL, RolEquipo.CIRUJANO_ASISTENTE})

    def tiene_habilitacion(self, especialidad: Especialidad, fecha: date) -> bool:
        return any(h.especialidad is especialidad and h.vigente_en(fecha) for h in self.habilitaciones)


class Anestesiologo(PersonalClinico):
    def rol_sistema(self) -> str:
        return "ANESTESIOLOGO"

    def roles_permitidos(self) -> frozenset[RolEquipo]:
        return frozenset({RolEquipo.ANESTESIOLOGO})


class Enfermero(PersonalClinico):
    def rol_sistema(self) -> str:
        return "ENFERMERO"

    def roles_permitidos(self) -> frozenset[RolEquipo]:
        return frozenset({RolEquipo.ENFERMERO_CIRCULANTE, RolEquipo.ENFERMERO_INSTRUMENTISTA})
