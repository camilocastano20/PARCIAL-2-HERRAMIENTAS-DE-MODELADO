"""Entidades y catálogos del dominio: Red, Hospital, Quirofano, EquipoMedico, Paciente,
Procedimiento, SolicitudCirugia, documentos clínicos, conteos e insumos."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Collection

from .enums import (
    EDAD_MAYORIA,
    EstadoCirugia,
    EstadoEquipo,
    EstadoEvaluacion,
    EstadoQuirofano,
    EstadoSolicitud,
    NivelContaminacion,
    RolEquipo,
    TipoConteo,
    TipoCirugia,
    TipoEquipo,
    TipoQuirofano,
    Especialidad,
)
from .excepciones import (
    ConflictoProgramacionError,
    GuardaIncumplidaError,
    TransicionInvalidaError,
)
from .politicas import PlanSeguro
from .valores import FranjaHoraria

if TYPE_CHECKING:
    from .cirugia import Cirugia, ReservaEquipo
    from .usuarios import Anestesiologo, Cirujano, Enfermero, PersonalClinico


# ------------------------------------------------------------------ catálogos
@dataclass(frozen=True)
class Procedimiento:
    codigo: str
    nombre: str
    especialidad: Especialidad
    duracion_estimada_min: int
    nivel_contaminacion: NivelContaminacion
    tipo_quirofano: TipoQuirofano
    tipos_equipo_requeridos: tuple[TipoEquipo, ...] = ()


@dataclass(frozen=True)
class Insumo:
    codigo: str
    nombre: str
    precio_unitario: Decimal


class CatalogoTarifas:
    """Honorarios por rol y tarifa por minuto por tipo de quirófano (RN14).
    Los valores se copian (congelan) en el momento de uso."""

    def __init__(self, honorarios: dict[RolEquipo, Decimal], tarifas_minuto: dict[TipoQuirofano, Decimal]) -> None:
        self._honorarios = dict(honorarios)
        self._tarifas = dict(tarifas_minuto)

    def honorario(self, rol: RolEquipo) -> Decimal:
        return self._honorarios[rol]

    def tarifa_minuto(self, tipo: TipoQuirofano) -> Decimal:
        return self._tarifas[tipo]

    def actualizar_tarifa_minuto(self, tipo: TipoQuirofano, valor: Decimal) -> None:
        self._tarifas[tipo] = valor


# ------------------------------------------------------------------ recursos
class EquipoMedico:
    def __init__(
        self,
        codigo_activo: str,
        tipo: TipoEquipo,
        estado: EstadoEquipo = EstadoEquipo.OPERATIVO,
        hospital: Hospital | None = None,
    ) -> None:
        self.codigo_activo = codigo_activo
        self.tipo = tipo
        self.estado = estado
        self.hospital = hospital
        self.reservas: list[ReservaEquipo] = []

    def esta_operativo(self) -> bool:
        return self.estado is EstadoEquipo.OPERATIVO

    def verificar_reservable(self, franja: FranjaHoraria, ignorando: Collection[Cirugia] = ()) -> None:
        """RN6: operativo y sin reservas solapadas."""
        if not self.esta_operativo():
            raise GuardaIncumplidaError("RN6", f"El equipo {self.codigo_activo} no está OPERATIVO ({self.estado.name}).")
        for r in self.reservas:
            if r.activa and r.cirugia.es_vigente() and r.cirugia not in ignorando and r.franja.solapa_con(franja):
                raise ConflictoProgramacionError(
                    "RN6", f"El equipo {self.codigo_activo} ya está reservado en una franja solapada."
                )


_TRANSICIONES_QUIROFANO: dict[tuple[EstadoQuirofano, str], EstadoQuirofano] = {
    (EstadoQuirofano.DISPONIBLE, "iniciar"): EstadoQuirofano.OCUPADO,
    (EstadoQuirofano.OCUPADO, "interrumpir"): EstadoQuirofano.OCUPADO,
    (EstadoQuirofano.OCUPADO, "reanudar"): EstadoQuirofano.OCUPADO,
    (EstadoQuirofano.OCUPADO, "finalizar_procedimiento"): EstadoQuirofano.EN_LIMPIEZA,
    (EstadoQuirofano.OCUPADO, "abortar"): EstadoQuirofano.EN_LIMPIEZA,
    (EstadoQuirofano.EN_LIMPIEZA, "registrar_limpieza_realizada"): EstadoQuirofano.DISPONIBLE,
    (EstadoQuirofano.DISPONIBLE, "iniciar_mantenimiento"): EstadoQuirofano.EN_MANTENIMIENTO,
    (EstadoQuirofano.EN_MANTENIMIENTO, "finalizar_mantenimiento"): EstadoQuirofano.DISPONIBLE,
}


class Quirofano:
    def __init__(
        self,
        codigo: str,
        piso: int,
        tipo: TipoQuirofano,
        estado: EstadoQuirofano = EstadoQuirofano.DISPONIBLE,
        hospital: Hospital | None = None,
    ) -> None:
        self.codigo = codigo
        self.piso = piso
        self.tipo = tipo
        self.estado = estado
        self.hospital = hospital
        self.cirugias: list[Cirugia] = []
        self.version = 0  # bloqueo optimista (Parte G-17)

    def es_compatible(self, procedimiento: Procedimiento) -> bool:
        return self.tipo is procedimiento.tipo_quirofano

    def conflictos(
        self, franja: FranjaHoraria, nivel: NivelContaminacion, ignorando: Collection[Cirugia] = ()
    ) -> list[Cirugia]:
        """RN1: cirugías vigentes que solapan o no respetan la limpieza mínima."""
        res: list[Cirugia] = []
        for c in self.cirugias:
            if not c.es_vigente() or c in ignorando:
                continue
            if c.franja.solapa_con(franja):
                res.append(c)
            elif c.franja.fin <= franja.inicio:
                if c.franja.separacion_hasta(franja) < c.solicitud.procedimiento.nivel_contaminacion.minutos_limpieza:
                    res.append(c)
            elif franja.separacion_hasta(c.franja) < nivel.minutos_limpieza:
                res.append(c)
        return res

    def verificar_disponibilidad(
        self, franja: FranjaHoraria, nivel: NivelContaminacion, ignorando: Collection[Cirugia] = ()
    ) -> None:
        conflictos = self.conflictos(franja, nivel, ignorando)
        if conflictos:
            raise ConflictoProgramacionError(
                "RN1",
                f"Quirófano {self.codigo}: la franja {franja.inicio:%H:%M}-{franja.fin:%H:%M} solapa o no respeta "
                f"la limpieza mínima respecto de la cirugía {conflictos[0].id}.",
            )

    def registrar_cirugia(self, cirugia: Cirugia) -> None:
        if cirugia not in self.cirugias:
            self.cirugias.append(cirugia)
        self.version += 1

    # --- máquina de estados de Quirófano (RN12) ---
    def aplicar_evento(self, evento: str) -> None:
        destino = _TRANSICIONES_QUIROFANO.get((self.estado, evento))
        if destino is None:
            raise TransicionInvalidaError(
                self.estado, evento, f"Quirófano {self.codigo}: evento '{evento}' inválido desde {self.estado.name}.", "RN12"
            )
        self.estado = destino

    def registrar_limpieza_realizada(self) -> None:
        self.aplicar_evento("registrar_limpieza_realizada")

    def iniciar_mantenimiento(self) -> None:
        self.aplicar_evento("iniciar_mantenimiento")

    def finalizar_mantenimiento(self) -> None:
        self.aplicar_evento("finalizar_mantenimiento")


class Hospital:
    def __init__(self, nombre: str) -> None:
        self.nombre = nombre
        self.red: Red | None = None
        self.quirofanos: list[Quirofano] = []
        self.equipos: list[EquipoMedico] = []
        self.personal: list[PersonalClinico] = []

    def agregar_quirofano(self, q: Quirofano) -> None:
        q.hospital = self
        self.quirofanos.append(q)

    def agregar_equipo(self, e: EquipoMedico) -> None:
        e.hospital = self
        self.equipos.append(e)

    def agregar_personal(self, p: PersonalClinico) -> None:
        self.personal.append(p)

    def buscar_quirofano_disponible(self, procedimiento: Procedimiento, franja: FranjaHoraria) -> Quirofano | None:
        for q in self.quirofanos:
            if (
                q.es_compatible(procedimiento)
                and q.estado is not EstadoQuirofano.EN_MANTENIMIENTO
                and not q.conflictos(franja, procedimiento.nivel_contaminacion)
            ):
                return q
        return None

    def candidatas_a_desplazar(self, procedimiento: Procedimiento, franja: FranjaHoraria) -> list[Cirugia]:
        """RN9: electivas PROGRAMADA/CONFIRMADA cuyo desplazamiento (solo ellas) libera el quirófano."""
        res: list[Cirugia] = []
        for q in self.quirofanos:
            if not q.es_compatible(procedimiento) or q.estado is EstadoQuirofano.EN_MANTENIMIENTO:
                continue
            conf = q.conflictos(franja, procedimiento.nivel_contaminacion)
            if len(conf) == 1 and conf[0].es_desplazable():
                res.append(conf[0])
        return res


class Red:
    def __init__(self, nombre: str) -> None:
        self.nombre = nombre
        self.hospitales: list[Hospital] = []

    def agregar_hospital(self, h: Hospital) -> None:
        h.red = self
        self.hospitales.append(h)


# ------------------------------------------------------------------ paciente y solicitud
class Paciente:
    def __init__(
        self,
        documento: str,
        nombre: str,
        fecha_nacimiento: date,
        grupo_sanguineo: str,
        asa: int,
        plan_seguro: PlanSeguro,
        alergias: tuple[str, ...] = (),
    ) -> None:
        if not 1 <= asa <= 5:
            raise ValueError("La clasificación ASA debe estar entre 1 y 5.")
        self.documento = documento
        self.nombre = nombre
        self.fecha_nacimiento = fecha_nacimiento
        self.grupo_sanguineo = grupo_sanguineo
        self.alergias = alergias
        self.asa = asa
        self.plan_seguro = plan_seguro

    def edad_en(self, fecha: date) -> int:
        n = self.fecha_nacimiento
        return fecha.year - n.year - ((fecha.month, fecha.day) < (n.month, n.day))

    def es_menor(self, fecha: date) -> bool:
        return self.edad_en(fecha) < EDAD_MAYORIA


class SolicitudCirugia:
    def __init__(
        self,
        id: str,
        cirujano: Cirujano,
        paciente: Paciente,
        procedimiento: Procedimiento,
        tipo: TipoCirugia,
        fecha_deseada: date,
        justificacion_clinica: str,
    ) -> None:
        self.id = id
        self.cirujano = cirujano
        self.paciente = paciente
        self.procedimiento = procedimiento
        self.tipo = tipo
        self.fecha_deseada = fecha_deseada
        self.justificacion_clinica = justificacion_clinica
        self.estado = EstadoSolicitud.PENDIENTE
        self.cirugia: Cirugia | None = None  # RN7: 0..1

    def esta_pendiente(self) -> bool:
        return self.estado is EstadoSolicitud.PENDIENTE

    def vincular_cirugia(self, cirugia: Cirugia) -> None:
        if self.cirugia is not None and self.cirugia is not cirugia:
            raise GuardaIncumplidaError("RN7", f"La solicitud {self.id} ya originó la cirugía {self.cirugia.id}.")
        self.cirugia = cirugia
        self.estado = EstadoSolicitud.ATENDIDA


# ------------------------------------------------------------------ documentos clínicos
@dataclass
class ConsentimientoInformado:
    firmante: str
    fecha_firma: datetime
    firmado: bool = True
    firmado_por_representante: bool = False


@dataclass
class EvaluacionPreanestesica:
    anestesiologo: Anestesiologo
    estado: EstadoEvaluacion
    fecha: datetime


@dataclass
class InformeOperatorio:
    firmado: bool
    firmado_por: Cirujano | None = None


@dataclass
class JustificacionEmergencia:
    texto: str
    firmante: Cirujano
    momento: datetime


@dataclass(frozen=True)
class ConteoInstrumental:
    tipo: TipoConteo
    total_contado: int
    total_esperado: int
    registrado_por: Enfermero
    momento: datetime

    @property
    def diferencia(self) -> int:
        """/diferencia = esperado - contado."""
        return self.total_esperado - self.total_contado


@dataclass
class IncidenteInstrumental:
    descripcion: str
    control_radiologico_resuelto: bool = False
