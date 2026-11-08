"""Enumeraciones y constantes del dominio SurgiPlan (Parte B-e / Parte E-12)."""
from __future__ import annotations

from enum import Enum


class EstadoCirugia(Enum):
    PROGRAMADA = "PROGRAMADA"
    CONFIRMADA = "CONFIRMADA"
    EN_CURSO = "EN_CURSO"
    INTERRUMPIDA = "INTERRUMPIDA"
    EN_RECUPERACION = "EN_RECUPERACION"
    COMPLETADA = "COMPLETADA"
    POSPUESTA = "POSPUESTA"
    CANCELADA = "CANCELADA"


# RN1: estados que "ocupan" quirófano, personal y equipos.
ESTADOS_VIGENTES: frozenset[EstadoCirugia] = frozenset(
    {
        EstadoCirugia.PROGRAMADA,
        EstadoCirugia.CONFIRMADA,
        EstadoCirugia.EN_CURSO,
        EstadoCirugia.INTERRUMPIDA,
    }
)


class TipoCirugia(Enum):
    ELECTIVA = "ELECTIVA"
    URGENTE = "URGENTE"
    EMERGENCIA = "EMERGENCIA"


class EstadoQuirofano(Enum):
    DISPONIBLE = "DISPONIBLE"
    OCUPADO = "OCUPADO"
    EN_LIMPIEZA = "EN_LIMPIEZA"
    EN_MANTENIMIENTO = "EN_MANTENIMIENTO"


class TipoQuirofano(Enum):
    GENERAL = "GENERAL"
    CARDIOVASCULAR = "CARDIOVASCULAR"
    ORTOPEDICO = "ORTOPEDICO"
    NEUROQUIRURGICO = "NEUROQUIRURGICO"


class EstadoEquipo(Enum):
    OPERATIVO = "OPERATIVO"
    EN_MANTENIMIENTO = "EN_MANTENIMIENTO"
    BAJA = "BAJA"


class TipoEquipo(Enum):
    ARCO_EN_C = "ARCO_EN_C"
    TORRE_LAPAROSCOPICA = "TORRE_LAPAROSCOPICA"
    MICROSCOPIO_QUIRURGICO = "MICROSCOPIO_QUIRURGICO"
    VENTILADOR = "VENTILADOR"


class NivelContaminacion(Enum):
    """El valor del miembro es el tiempo mínimo de limpieza (RN1), en minutos."""

    LIMPIA = 20
    LIMPIA_CONTAMINADA = 30
    CONTAMINADA = 45
    SUCIA = 60

    @property
    def minutos_limpieza(self) -> int:
        return int(self.value)


class RolEquipo(Enum):
    CIRUJANO_PRINCIPAL = "CIRUJANO_PRINCIPAL"
    CIRUJANO_ASISTENTE = "CIRUJANO_ASISTENTE"
    ANESTESIOLOGO = "ANESTESIOLOGO"
    ENFERMERO_CIRCULANTE = "ENFERMERO_CIRCULANTE"
    ENFERMERO_INSTRUMENTISTA = "ENFERMERO_INSTRUMENTISTA"
    OBSERVADOR = "OBSERVADOR"  # extensión G-16: no altera RN2 (rol no único, no obligatorio)


# RN2: roles de los que existe "exactamente uno" por cirugía.
ROLES_UNICOS: frozenset[RolEquipo] = frozenset(
    {RolEquipo.CIRUJANO_PRINCIPAL, RolEquipo.ANESTESIOLOGO, RolEquipo.ENFERMERO_CIRCULANTE}
)


class FaseClinica(Enum):
    """Región ortogonal 1 de EN_CURSO."""

    INDUCCION = "INDUCCION"
    PROCEDIMIENTO = "PROCEDIMIENTO"
    CIERRE = "CIERRE"


class EstadoConteo(Enum):
    """Región ortogonal 2 de EN_CURSO (control de instrumental)."""

    SIN_CONTEO = "SIN_CONTEO"
    CONTEO_INICIAL_REGISTRADO = "CONTEO_INICIAL_REGISTRADO"
    CONTEO_FINAL_VERIFICADO = "CONTEO_FINAL_VERIFICADO"


class TipoConteo(Enum):
    INICIAL = "INICIAL"
    FINAL = "FINAL"


class EstadoEvaluacion(Enum):
    PENDIENTE = "PENDIENTE"
    APROBADA = "APROBADA"
    RECHAZADA = "RECHAZADA"


class EstadoSolicitud(Enum):
    PENDIENTE = "PENDIENTE"
    ATENDIDA = "ATENDIDA"
    RECHAZADA = "RECHAZADA"


class Especialidad(Enum):
    CIRUGIA_GENERAL = "CIRUGIA_GENERAL"
    CARDIOVASCULAR = "CARDIOVASCULAR"
    ORTOPEDIA = "ORTOPEDIA"
    NEUROCIRUGIA = "NEUROCIRUGIA"


class MotivoCancelacion(Enum):
    """Catálogo de motivos de cancelación (RN13)."""

    DESISTIMIENTO_PACIENTE = "DESISTIMIENTO_PACIENTE"
    PACIENTE_NO_APTO = "PACIENTE_NO_APTO"
    FALTA_DE_RECURSOS = "FALTA_DE_RECURSOS"
    ERROR_DE_PROGRAMACION = "ERROR_DE_PROGRAMACION"
    OTRO_CATALOGADO = "OTRO_CATALOGADO"


class ActorAutorizado(Enum):
    """Quién puede disparar un evento (RN16)."""

    COORDINADOR = "COORDINADOR"
    CIRUJANO_PRINCIPAL = "CIRUJANO_PRINCIPAL"
    ENFERMERO_CIRCULANTE = "ENFERMERO_CIRCULANTE"
    SISTEMA = "SISTEMA"


# --- Constantes de reglas de negocio -------------------------------------
TOPE_DIARIO_MINUTOS: int = 12 * 60          # RN3
UMBRAL_ASA_RECARGO: int = 3                 # RN5
RECARGO_ASA_PORCENTAJE: int = 25            # RN5
MINUTOS_VENCIMIENTO_CONFIRMACION: int = 45  # RN10
ANTIGUEDAD_MAX_CONSENTIMIENTO_DIAS: int = 30  # RN8
HORAS_PLAZO_CONSENTIMIENTO_EMERGENCIA: int = 24  # RN8
HORAS_CANCELACION_TARDIA: int = 24          # RN13
ALDRETE_MINIMO: int = 9                     # alta
EDAD_MAYORIA: int = 18                      # RN8
