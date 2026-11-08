"""Objetos de valor: FranjaHoraria, Habilitacion, EventoAuditoria (Parte B-d)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .enums import Especialidad, EstadoCirugia
from .excepciones import FranjaInvalidaError


@dataclass(frozen=True)
class FranjaHoraria:
    """Intervalo semiabierto [inicio, fin). Inmutable; igualdad por valor."""

    inicio: datetime
    fin: datetime

    def __post_init__(self) -> None:
        if (self.inicio.tzinfo is None) != (self.fin.tzinfo is None):
            raise FranjaInvalidaError("inicio y fin deben ser ambos naive o ambos con zona horaria.")
        if self.fin <= self.inicio:
            raise FranjaInvalidaError(f"fin ({self.fin}) debe ser posterior a inicio ({self.inicio}).")

    def duracion(self) -> timedelta:
        return self.fin - self.inicio

    def duracion_minutos(self) -> int:
        return int(self.duracion().total_seconds() // 60)

    def solapa_con(self, otra: FranjaHoraria) -> bool:
        """Intervalos semiabiertos: [8:00,10:00) y [10:00,12:00) NO se solapan."""
        return self.inicio < otra.fin and otra.inicio < self.fin

    def separacion_hasta(self, otra: FranjaHoraria) -> int:
        """Minutos entre self.fin y otra.inicio (negativo si se solapan o otra no la sucede)."""
        return int((otra.inicio - self.fin).total_seconds() // 60)

    def dias(self) -> tuple[date, ...]:
        resultado: list[date] = []
        dia = self.inicio.date()
        ultimo = (self.fin - timedelta(microseconds=1)).date()
        while dia <= ultimo:
            resultado.append(dia)
            dia += timedelta(days=1)
        return tuple(resultado)

    def minutos_en_dia(self, dia: date) -> int:
        """Minutos de la franja que caen en el día calendario `dia` (prorrateo, ASUNCIÓN 6)."""
        ini_dia = datetime.combine(dia, time.min, tzinfo=self.inicio.tzinfo)
        fin_dia = ini_dia + timedelta(days=1)
        ini = max(self.inicio, ini_dia)
        fin = min(self.fin, fin_dia)
        return max(0, int((fin - ini).total_seconds() // 60))


@dataclass(frozen=True)
class Habilitacion:
    especialidad: Especialidad
    vencimiento: date

    def vigente_en(self, fecha: date) -> bool:
        """RN4: vencimiento posterior o igual a la fecha de la cirugía."""
        return self.vencimiento >= fecha


@dataclass(frozen=True)
class EventoAuditoria:
    """Inmutable (RN15)."""

    cirugia_id: str
    estado_origen: EstadoCirugia | None
    estado_destino: EstadoCirugia
    momento: datetime
    usuario: str
    motivo: str | None = None
    evento: str = ""
