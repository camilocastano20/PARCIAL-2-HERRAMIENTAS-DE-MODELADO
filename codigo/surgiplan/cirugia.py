"""Cirugia, clases de asociación y máquina de estados declarativa (Partes D y E)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from math import ceil
from typing import Any, Callable, Collection

from .dominio import (
    CatalogoTarifas,
    ConsentimientoInformado,
    ConteoInstrumental,
    EquipoMedico,
    EvaluacionPreanestesica,
    IncidenteInstrumental,
    Insumo,
    InformeOperatorio,
    JustificacionEmergencia,
    Quirofano,
    SolicitudCirugia,
)
from .enums import (
    ALDRETE_MINIMO,
    ANTIGUEDAD_MAX_CONSENTIMIENTO_DIAS,
    ESTADOS_VIGENTES,
    HORAS_CANCELACION_TARDIA,
    HORAS_PLAZO_CONSENTIMIENTO_EMERGENCIA,
    MINUTOS_VENCIMIENTO_CONFIRMACION,
    ROLES_UNICOS,
    UMBRAL_ASA_RECARGO,
    ActorAutorizado,
    EstadoCirugia,
    EstadoConteo,
    EstadoEquipo,
    EstadoEvaluacion,
    EstadoQuirofano,
    FaseClinica,
    MotivoCancelacion,
    RolEquipo,
    TipoCirugia,
    TipoConteo,
)
from .excepciones import (
    ConflictoProgramacionError,
    ConflictoVersionError,
    GuardaIncumplidaError,
    PermisoDenegadoError,
    TransicionInvalidaError,
)
from .politicas import CanalNotificacion, DuracionConRecargoAsa, DuracionEstandar, EstrategiaDuracion
from .usuarios import Anestesiologo, Cirujano, Coordinador, Enfermero, PersonalClinico, Usuario
from .valores import EventoAuditoria, FranjaHoraria

_ESTADOS_EDITABLES: frozenset[EstadoCirugia | None] = frozenset({None, EstadoCirugia.PROGRAMADA, EstadoCirugia.POSPUESTA})


# ------------------------------------------------------------ clases de asociación
class AsignacionProfesional:
    """Clase de asociación Cirugia–PersonalClinico con el atributo `rol` (RN2/RN3)."""

    def __init__(self, cirugia: Cirugia, profesional: PersonalClinico, rol: RolEquipo, honorario_congelado: Decimal) -> None:
        self.cirugia = cirugia
        self.profesional = profesional
        self.rol = rol
        self.honorario_congelado = honorario_congelado  # RN14


class ReservaEquipo:
    def __init__(self, cirugia: Cirugia, equipo: EquipoMedico, franja: FranjaHoraria) -> None:
        self.cirugia = cirugia
        self.equipo = equipo
        self.franja = franja
        self.activa = True

    def liberar(self) -> None:
        self.activa = False


class ConsumoInsumo:
    def __init__(self, cirugia: Cirugia, insumo: Insumo, cantidad: int, momento: datetime) -> None:
        if cantidad <= 0:
            raise GuardaIncumplidaError("RN14", "La cantidad consumida debe ser positiva.")
        self.cirugia = cirugia
        self.insumo = insumo
        self.cantidad = cantidad
        self.precio_unitario = insumo.precio_unitario  # congelado al momento de uso (RN14)
        self.momento = momento

    def subtotal(self) -> Decimal:
        return self.precio_unitario * self.cantidad


# ------------------------------------------------------------ infraestructura de la máquina
@dataclass
class Contexto:
    actor: Usuario | None
    ahora: datetime
    motivo: str | None = None
    datos: dict[str, Any] = field(default_factory=dict)


Guarda = Callable[["Cirugia", Contexto], None]
Efecto = Callable[["Cirugia", Contexto], None]


@dataclass(frozen=True)
class Transicion:
    origen: EstadoCirugia | None
    evento: str
    destino: EstadoCirugia
    actor: ActorAutorizado
    guardas: tuple[Guarda, ...] = ()
    efectos: tuple[Efecto, ...] = ()


@dataclass(frozen=True)
class TransicionInterna:
    """Transición dentro de una región ortogonal de EN_CURSO."""

    region: str
    origen: FaseClinica | EstadoConteo
    evento: str
    destino: FaseClinica | EstadoConteo
    actor: ActorAutorizado
    guardas: tuple[Guarda, ...] = ()
    efectos: tuple[Efecto, ...] = ()


# ------------------------------------------------------------ guardas
def g_programacion(c: Cirugia, ctx: Contexto) -> None:
    v = ctx.datos.get("version_quirofano")
    if v is not None and v != c.quirofano.version:
        raise ConflictoVersionError("RN1", f"El quirófano {c.quirofano.codigo} cambió (versión {c.quirofano.version} != {v}); reintente.")
    c.validar_programacion(ctx.ahora)


def g_confirmacion(c: Cirugia, ctx: Contexto) -> None:
    """RN8."""
    if c.solicitud.tipo is TipoCirugia.EMERGENCIA:
        j = c.justificacion_emergencia
        if j is None or j.firmante is not c.cirujano_principal():
            raise GuardaIncumplidaError("RN8", "EMERGENCIA: se exige justificación firmada por el cirujano principal.")
        return
    k = c.consentimiento
    fecha_cx = c.franja.inicio.date()
    if k is None or not k.firmado:
        raise GuardaIncumplidaError("RN8", "Se exige consentimiento informado firmado.")
    if c.solicitud.paciente.es_menor(fecha_cx) and not k.firmado_por_representante:
        raise GuardaIncumplidaError("RN8", "Paciente menor de 18 años: el consentimiento debe firmarlo su representante legal.")
    antig = (fecha_cx - k.fecha_firma.date()).days
    if antig < 0 or antig > ANTIGUEDAD_MAX_CONSENTIMIENTO_DIAS:
        raise GuardaIncumplidaError("RN8", f"Consentimiento con antigüedad {antig} d (máximo {ANTIGUEDAD_MAX_CONSENTIMIENTO_DIAS}).")
    ev = c.evaluacion_preanestesica
    if ev is None or ev.estado is not EstadoEvaluacion.APROBADA:
        raise GuardaIncumplidaError("RN8", "Se exige evaluación preanestésica APROBADA.")


def g_inicio(c: Cirugia, ctx: Contexto) -> None:
    if ctx.ahora > c.franja.inicio + timedelta(minutes=MINUTOS_VENCIMIENTO_CONFIRMACION):
        raise GuardaIncumplidaError("RN10", "Pasaron más de 45 min del inicio programado: la cirugía debe pasar a POSPUESTA.")
    if c.quirofano.estado is not EstadoQuirofano.DISPONIBLE:
        raise GuardaIncumplidaError("RN12", f"El quirófano {c.quirofano.codigo} no está DISPONIBLE ({c.quirofano.estado.name}).")


def g_reanudar(c: Cirugia, ctx: Contexto) -> None:
    if c._historia is None:
        raise GuardaIncumplidaError("RN10", "No hay historia (H*) guardada para reanudar.")


def g_finalizacion(c: Cirugia, ctx: Contexto) -> None:
    """RN11 (join de las dos regiones)."""
    if c.fase_clinica is not FaseClinica.CIERRE:
        raise GuardaIncumplidaError("RN11", "No se puede finalizar: la fase CIERRE no se ha completado.")
    if c.control_instrumental is not EstadoConteo.CONTEO_FINAL_VERIFICADO:
        raise GuardaIncumplidaError("RN11", "No se puede finalizar: el conteo final de instrumental no está verificado.")


def g_aborto(c: Cirugia, ctx: Contexto) -> None:
    if not ctx.motivo:
        raise GuardaIncumplidaError("RN10", "El aborto clínico exige un motivo.")


def g_alta(c: Cirugia, ctx: Contexto) -> None:
    if c.informe_operatorio is None or not c.informe_operatorio.firmado:
        raise GuardaIncumplidaError("ALTA", "Para el alta se exige el informe operatorio firmado.")
    if c.puntuacion_aldrete is None or c.puntuacion_aldrete < ALDRETE_MINIMO:
        raise GuardaIncumplidaError("ALTA", f"Para el alta se exige Aldrete >= {ALDRETE_MINIMO}.")


def g_desplazable(c: Cirugia, ctx: Contexto) -> None:
    emergencia = ctx.datos.get("emergencia")
    if not isinstance(emergencia, Cirugia) or emergencia.solicitud.tipo is not TipoCirugia.EMERGENCIA:
        raise GuardaIncumplidaError("RN9", "Solo una cirugía de tipo EMERGENCIA puede desplazar a otra.")
    if c.solicitud.tipo is not TipoCirugia.ELECTIVA:
        raise GuardaIncumplidaError("RN9", "Nunca se desplaza una cirugía URGENTE o EMERGENCIA; solo ELECTIVA.")


def g_cancelacion(c: Cirugia, ctx: Contexto) -> None:
    """RN13."""
    if not isinstance(ctx.datos.get("motivo_cancelacion"), MotivoCancelacion):
        raise GuardaIncumplidaError("RN13", "La cancelación exige un motivo del catálogo.")
    if ctx.actor is None:
        raise GuardaIncumplidaError("RN13", "La cancelación exige el usuario que cancela.")


def g_vencimiento(c: Cirugia, ctx: Contexto) -> None:
    if ctx.ahora <= c.franja.inicio + timedelta(minutes=MINUTOS_VENCIMIENTO_CONFIRMACION):
        raise GuardaIncumplidaError("RN10", "Aún no han transcurrido 45 min desde el inicio programado.")


def g_entrar_cierre(c: Cirugia, ctx: Contexto) -> None:
    """RN11: [in(CONTEO_INICIAL_REGISTRADO)]."""
    if c.control_instrumental is EstadoConteo.SIN_CONTEO:
        raise GuardaIncumplidaError("RN11", "No se puede entrar a CIERRE sin conteo inicial registrado.")


def g_verificar_conteo(c: Cirugia, ctx: Contexto) -> None:
    """RN11: [in(CIERRE)] y (diferencia = 0 o incidente con control radiológico resuelto)."""
    if c.fase_clinica is not FaseClinica.CIERRE:
        raise GuardaIncumplidaError("RN11", "El conteo final solo se verifica en la fase CIERRE.")
    if c.conteo_final is None:
        raise GuardaIncumplidaError("RN11", "Falta registrar el conteo final.")
    if c.conteo_final.diferencia != 0 and not any(i.control_radiologico_resuelto for i in c.incidentes):
        raise GuardaIncumplidaError(
            "RN11", f"Conteo final con diferencia {c.conteo_final.diferencia} y sin incidente con control radiológico resuelto."
        )


# ------------------------------------------------------------ efectos
def e_programar(c: Cirugia, ctx: Contexto) -> None:
    c.momento_programacion = ctx.ahora
    c.solicitud.vincular_cirugia(c)
    c.quirofano.registrar_cirugia(c)
    for r in c.reservas:
        if r.activa and r not in r.equipo.reservas:
            r.equipo.reservas.append(r)


def e_confirmar(c: Cirugia, ctx: Contexto) -> None:
    if c.solicitud.tipo is TipoCirugia.EMERGENCIA:
        c.limite_consentimiento = ctx.ahora + timedelta(hours=HORAS_PLAZO_CONSENTIMIENTO_EMERGENCIA)


def e_liberar(c: Cirugia, ctx: Contexto) -> None:
    c.liberar_reservas()


def e_desplazar(c: Cirugia, ctx: Contexto) -> None:
    c.liberar_reservas()
    c._motivo_ultimo = f"Desplazada por emergencia {ctx.datos['emergencia'].id}"
    ctx.motivo = c._motivo_ultimo


def e_cancelar(c: Cirugia, ctx: Contexto) -> None:
    origen_pospuesta = ctx.datos.get("_origen") is EstadoCirugia.POSPUESTA
    c.motivo_cancelacion = ctx.datos["motivo_cancelacion"]
    ctx.motivo = c.motivo_cancelacion.name if c.motivo_cancelacion else None
    if not origen_pospuesta and c.franja.inicio - ctx.ahora < timedelta(hours=HORAS_CANCELACION_TARDIA):
        c.cancelacion_tardia = True
        c.cargo_administrativo = c.solicitud.paciente.plan_seguro.calcular_cargo_cancelacion_tardia()
    c.liberar_reservas()


def e_iniciar(c: Cirugia, ctx: Contexto) -> None:
    c.quirofano.aplicar_evento("iniciar")
    c.fase_clinica = FaseClinica.INDUCCION
    c.control_instrumental = EstadoConteo.SIN_CONTEO
    c._historia = None
    c._inicio_tramo = ctx.ahora
    c.tarifa_minuto_congelada = c.catalogo.tarifa_minuto(c.quirofano.tipo)


def e_interrumpir(c: Cirugia, ctx: Contexto) -> None:
    assert c.fase_clinica is not None
    c._historia = (c.fase_clinica, c.control_instrumental)  # H*: historia profunda
    c._cerrar_tramo(ctx.ahora)
    c.quirofano.aplicar_evento("interrumpir")


def e_reanudar(c: Cirugia, ctx: Contexto) -> None:
    assert c._historia is not None
    c.fase_clinica, c.control_instrumental = c._historia
    c._inicio_tramo = ctx.ahora
    c.quirofano.aplicar_evento("reanudar")


def e_finalizar(c: Cirugia, ctx: Contexto) -> None:
    c._cerrar_tramo(ctx.ahora)
    c.quirofano.aplicar_evento("finalizar_procedimiento")
    c.liberar_reservas()
    c._historia = None


def e_abortar(c: Cirugia, ctx: Contexto) -> None:
    c.abortada = True
    c.quirofano.aplicar_evento("abortar")
    c.liberar_reservas()
    c._historia = None


def e_a_procedimiento(c: Cirugia, ctx: Contexto) -> None:
    pass


# ------------------------------------------------------------ tablas declarativas
_C, _P, _S = ActorAutorizado.COORDINADOR, ActorAutorizado.CIRUJANO_PRINCIPAL, ActorAutorizado.SISTEMA
_E = EstadoCirugia

TRANSICIONES: dict[tuple[EstadoCirugia | None, str], Transicion] = {
    (t.origen, t.evento): t
    for t in (
        Transicion(None, "programar", _E.PROGRAMADA, _C, (g_programacion,), (e_programar,)),
        Transicion(_E.PROGRAMADA, "confirmar", _E.CONFIRMADA, _C, (g_confirmacion,), (e_confirmar,)),
        Transicion(_E.PROGRAMADA, "posponer", _E.POSPUESTA, _C, (), (e_liberar,)),
        Transicion(_E.CONFIRMADA, "posponer", _E.POSPUESTA, _C, (), (e_liberar,)),
        Transicion(_E.PROGRAMADA, "desplazar_por_emergencia", _E.POSPUESTA, _C, (g_desplazable,), (e_desplazar,)),
        Transicion(_E.CONFIRMADA, "desplazar_por_emergencia", _E.POSPUESTA, _C, (g_desplazable,), (e_desplazar,)),
        Transicion(_E.CONFIRMADA, "vencer_confirmacion", _E.POSPUESTA, _S, (g_vencimiento,), (e_liberar,)),
        Transicion(_E.POSPUESTA, "reprogramar", _E.PROGRAMADA, _C, (g_programacion,), (e_programar,)),
        Transicion(_E.PROGRAMADA, "cancelar", _E.CANCELADA, _C, (g_cancelacion,), (e_cancelar,)),
        Transicion(_E.CONFIRMADA, "cancelar", _E.CANCELADA, _C, (g_cancelacion,), (e_cancelar,)),
        Transicion(_E.POSPUESTA, "cancelar", _E.CANCELADA, _C, (g_cancelacion,), (e_cancelar,)),
        Transicion(_E.CONFIRMADA, "iniciar", _E.EN_CURSO, _P, (g_inicio,), (e_iniciar,)),
        Transicion(_E.EN_CURSO, "interrumpir", _E.INTERRUMPIDA, _P, (), (e_interrumpir,)),
        Transicion(_E.INTERRUMPIDA, "reanudar", _E.EN_CURSO, _P, (g_reanudar,), (e_reanudar,)),
        Transicion(_E.EN_CURSO, "finalizar_procedimiento", _E.EN_RECUPERACION, _P, (g_finalizacion,), (e_finalizar,)),
        Transicion(_E.INTERRUMPIDA, "abortar", _E.EN_RECUPERACION, _P, (g_aborto,), (e_abortar,)),
        Transicion(_E.EN_RECUPERACION, "dar_alta", _E.COMPLETADA, _P, (g_alta,), ()),
    )
}

_F, _K = FaseClinica, EstadoConteo
_CIRC = ActorAutorizado.ENFERMERO_CIRCULANTE
TRANSICIONES_INTERNAS: dict[str, TransicionInterna] = {
    t.evento: t
    for t in (
        TransicionInterna("fase_clinica", _F.INDUCCION, "pasar_a_procedimiento", _F.PROCEDIMIENTO, _P),
        TransicionInterna("fase_clinica", _F.PROCEDIMIENTO, "entrar_cierre", _F.CIERRE, _P, (g_entrar_cierre,)),
        TransicionInterna("control_instrumental", _K.SIN_CONTEO, "registrar_conteo_inicial", _K.CONTEO_INICIAL_REGISTRADO, _CIRC),
        TransicionInterna("control_instrumental", _K.CONTEO_INICIAL_REGISTRADO, "verificar_conteo_final", _K.CONTEO_FINAL_VERIFICADO, _CIRC, (g_verificar_conteo,)),
    )
}

_PROHIBIDAS: dict[tuple[EstadoCirugia | None, str], tuple[str, str]] = {
    (_E.EN_CURSO, "cancelar"): ("RN10", "Una cirugía EN_CURSO no puede cancelarse."),
    (_E.INTERRUMPIDA, "cancelar"): ("RN10", "Una cirugía INTERRUMPIDA no puede cancelarse."),
    (_E.CANCELADA, "reprogramar"): ("RN10", "Una cirugía CANCELADA no puede volver a PROGRAMADA."),
    (_E.CANCELADA, "posponer"): ("RN10", "Una cirugía CANCELADA no puede pasar a POSPUESTA."),
    (_E.EN_CURSO, "desplazar_por_emergencia"): ("RN9", "Nunca se desplaza una cirugía EN_CURSO."),
    (_E.INTERRUMPIDA, "desplazar_por_emergencia"): ("RN9", "Nunca se desplaza una cirugía INTERRUMPIDA."),
}


# ------------------------------------------------------------ Cirugia
class Cirugia:
    def __init__(
        self,
        id: str,
        solicitud: SolicitudCirugia,
        quirofano: Quirofano,
        franja: FranjaHoraria,
        coordinador: Coordinador,
        catalogo: CatalogoTarifas,
        canales: Collection[CanalNotificacion] = (),
        estrategia_duracion: EstrategiaDuracion | None = None,
    ) -> None:
        self.id = id
        self.solicitud = solicitud
        self.quirofano = quirofano
        self.franja = franja
        self.coordinador = coordinador
        self.catalogo = catalogo
        self.canales: list[CanalNotificacion] = list(canales)
        self.estado: EstadoCirugia | None = None
        # asociación calificada: [identificacion] -> 0..1 AsignacionProfesional (un rol por profesional)
        self.asignaciones: dict[str, AsignacionProfesional] = {}
        self.reservas: list[ReservaEquipo] = []
        self.consumos: list[ConsumoInsumo] = []
        self.eventos: list[EventoAuditoria] = []
        self.incidentes: list[IncidenteInstrumental] = []
        self.conteo_inicial: ConteoInstrumental | None = None
        self.conteo_final: ConteoInstrumental | None = None
        self.fase_clinica: FaseClinica | None = None
        self.control_instrumental: EstadoConteo = EstadoConteo.SIN_CONTEO
        self._historia: tuple[FaseClinica, EstadoConteo] | None = None
        self.consentimiento: ConsentimientoInformado | None = None
        self.evaluacion_preanestesica: EvaluacionPreanestesica | None = None
        self.informe_operatorio: InformeOperatorio | None = None
        self.justificacion_emergencia: JustificacionEmergencia | None = None
        self.limite_consentimiento: datetime | None = None
        self.puntuacion_aldrete: int | None = None
        self.motivo_cancelacion: MotivoCancelacion | None = None
        self.cancelacion_tardia = False
        self.cargo_administrativo = Decimal("0")
        self.momento_programacion: datetime | None = None
        self.minutos_reales = 0
        self._inicio_tramo: datetime | None = None
        self.tarifa_minuto_congelada: Decimal | None = None
        self.abortada = False
        self.version = 0
        self.fallos_notificacion: list[tuple[CanalNotificacion, Exception]] = []
        self._candidata: Cirugia | None = None
        self._motivo_ultimo: str | None = None
        # Strategy (RN5): opt [paciente.asa >= 3]
        self.estrategia_duracion: EstrategiaDuracion = DuracionEstandar()
        if estrategia_duracion is not None:
            self.usar_estrategia_duracion(estrategia_duracion)
        elif solicitud.paciente.asa >= UMBRAL_ASA_RECARGO:
            self.usar_estrategia_duracion(DuracionConRecargoAsa())

    # ---------------------------------------------------------- consultas
    def es_vigente(self) -> bool:
        return self.estado in ESTADOS_VIGENTES

    def es_desplazable(self) -> bool:
        return self.solicitud.tipo is TipoCirugia.ELECTIVA and self.estado in (EstadoCirugia.PROGRAMADA, EstadoCirugia.CONFIRMADA)

    def equipo_quirurgico(self) -> list[AsignacionProfesional]:
        return list(self.asignaciones.values())

    def _con_rol(self, rol: RolEquipo) -> list[PersonalClinico]:
        return [a.profesional for a in self.asignaciones.values() if a.rol is rol]

    def cirujano_principal(self) -> Cirujano | None:
        p = self._con_rol(RolEquipo.CIRUJANO_PRINCIPAL)
        return p[0] if p and isinstance(p[0], Cirujano) else None

    def anestesiologo(self) -> Anestesiologo | None:
        p = self._con_rol(RolEquipo.ANESTESIOLOGO)
        return p[0] if p and isinstance(p[0], Anestesiologo) else None

    def enfermero_circulante(self) -> Enfermero | None:
        p = self._con_rol(RolEquipo.ENFERMERO_CIRCULANTE)
        return p[0] if p and isinstance(p[0], Enfermero) else None

    @property
    def duracion_programada(self) -> int:
        """/duracion_programada (minutos)."""
        return self.franja.duracion_minutos()

    def duracion_minima(self) -> int:
        return self.estrategia_duracion.minutos_minimos(self.solicitud.procedimiento, self.solicitud.paciente)

    @property
    def costo_total(self) -> Decimal:
        """/costo_total (RN14)."""
        honorarios = sum((a.honorario_congelado for a in self.asignaciones.values()), Decimal("0"))
        tiempo = Decimal(self.minutos_reales) * (self.tarifa_minuto_congelada or Decimal("0"))
        insumos = sum((c.subtotal() for c in self.consumos), Decimal("0"))
        return honorarios + tiempo + insumos

    def valor_a_cargo_paciente(self) -> Decimal:
        return self.solicitud.paciente.plan_seguro.calcular_copago(self.costo_total)

    def reservas_activas(self) -> list[ReservaEquipo]:
        return [r for r in self.reservas if r.activa]

    # ---------------------------------------------------------- preparación
    def usar_estrategia_duracion(self, estrategia: EstrategiaDuracion) -> None:
        self.estrategia_duracion = estrategia

    def marcar_candidata_a_desplazar(self, candidata: Cirugia | None) -> None:
        """RN9: las validaciones tratarán a `candidata` como si ya no estuviera vigente."""
        self._candidata = candidata

    def _ignoradas(self) -> frozenset[Cirugia]:
        return frozenset({self} | ({self._candidata} if self._candidata else set()))

    def asignar_profesional(self, profesional: PersonalClinico, rol: RolEquipo) -> AsignacionProfesional:
        if self.estado not in _ESTADOS_EDITABLES:
            raise GuardaIncumplidaError("RN2", f"No se puede modificar el equipo en estado {self.estado}.")
        if not profesional.activo:
            raise GuardaIncumplidaError("RN2", f"El profesional {profesional.nombre} no está activo.")
        if rol not in profesional.roles_permitidos():
            raise GuardaIncumplidaError("RN2", f"{profesional.nombre} no puede desempeñar el rol {rol.name}.")
        if profesional.identificacion in self.asignaciones:
            raise GuardaIncumplidaError("RN2", f"{profesional.nombre} ya tiene un rol en esta cirugía (un solo rol por cirugía).")
        if rol in ROLES_UNICOS and self._con_rol(rol):
            raise GuardaIncumplidaError("RN2", f"Ya existe un {rol.name}: debe haber exactamente uno.")
        if rol is RolEquipo.CIRUJANO_PRINCIPAL:
            assert isinstance(profesional, Cirujano)
            self._validar_habilitacion(profesional)
        self._validar_rn3(profesional)
        asignacion = AsignacionProfesional(self, profesional, rol, self.catalogo.honorario(rol))
        self.asignaciones[profesional.identificacion] = asignacion
        profesional.asignaciones.append(asignacion)
        return asignacion

    def reservar_equipo(self, equipo: EquipoMedico) -> ReservaEquipo:
        if self.estado not in _ESTADOS_EDITABLES:
            raise GuardaIncumplidaError("RN6", f"No se pueden reservar equipos en estado {self.estado}.")
        if equipo.tipo not in self.solicitud.procedimiento.tipos_equipo_requeridos:
            raise GuardaIncumplidaError("RN6", f"El tipo {equipo.tipo.name} no es requerido por el procedimiento.")
        if any(r.equipo.tipo is equipo.tipo for r in self.reservas_activas()):
            raise GuardaIncumplidaError("RN6", f"Ya hay un equipo {equipo.tipo.name} reservado (uno por tipo).")
        equipo.verificar_reservable(self.franja, self._ignoradas())
        reserva = ReservaEquipo(self, equipo, self.franja)
        self.reservas.append(reserva)
        equipo.reservas.append(reserva)
        return reserva

    def liberar_reservas(self) -> None:
        for r in self.reservas:
            r.liberar()

    # ---------------------------------------------------------- validaciones
    def _validar_habilitacion(self, cirujano: Cirujano) -> None:
        """RN4 (sub-diagrama «Validar habilitación»)."""
        esp = self.solicitud.procedimiento.especialidad
        if not cirujano.tiene_habilitacion(esp, self.franja.inicio.date()):
            raise GuardaIncumplidaError("RN4", f"{cirujano.nombre} no tiene habilitación vigente en {esp.name} a la fecha de la cirugía.")

    def _validar_rn3(self, profesional: PersonalClinico) -> None:
        ign = self._ignoradas()
        if profesional.tiene_solapamiento(self.franja, ign):
            raise ConflictoProgramacionError("RN3", f"{profesional.nombre} tiene otra cirugía vigente con franja solapada.")
        if profesional.excede_tope_diario(self.franja, ign):
            raise ConflictoProgramacionError("RN3", f"{profesional.nombre} excedería el tope de 12 h de franjas en un día calendario.")

    def _validar_rn2(self) -> None:
        def n(rol: RolEquipo) -> int:
            return len(self._con_rol(rol))

        if n(RolEquipo.CIRUJANO_PRINCIPAL) != 1:
            raise GuardaIncumplidaError("RN2", "Se requiere exactamente un cirujano principal.")
        if n(RolEquipo.ANESTESIOLOGO) != 1:
            raise GuardaIncumplidaError("RN2", "Se requiere exactamente un anestesiólogo.")
        if n(RolEquipo.ENFERMERO_CIRCULANTE) != 1:
            raise GuardaIncumplidaError("RN2", "Se requiere exactamente un enfermero circulante.")
        if n(RolEquipo.ENFERMERO_INSTRUMENTISTA) < 1:
            raise GuardaIncumplidaError("RN2", "Se requiere al menos un enfermero instrumentista.")
        if any(not a.profesional.activo for a in self.asignaciones.values()):
            raise GuardaIncumplidaError("RN2", "Todos los profesionales asignados deben estar activos.")

    def _validar_rn5(self, ahora: datetime) -> None:
        minimo = self.duracion_minima()
        if self.duracion_programada < minimo:
            raise GuardaIncumplidaError("RN5", f"La franja dura {self.duracion_programada} min y el mínimo es {minimo} min.")
        if self.solicitud.tipo is not TipoCirugia.EMERGENCIA and self.franja.inicio < ahora:
            raise GuardaIncumplidaError("RN5", "El inicio no puede ser anterior al momento de programación (salvo EMERGENCIA).")

    def _validar_rn6(self) -> None:
        proc = self.solicitud.procedimiento
        if not self.quirofano.es_compatible(proc):
            raise GuardaIncumplidaError("RN6", f"El quirófano {self.quirofano.codigo} no es de tipo {proc.tipo_quirofano.name}.")
        if self.quirofano.estado is EstadoQuirofano.EN_MANTENIMIENTO:
            raise GuardaIncumplidaError("RN6", f"El quirófano {self.quirofano.codigo} está EN_MANTENIMIENTO.")
        activas = self.reservas_activas()
        for tipo in proc.tipos_equipo_requeridos:
            if not any(r.equipo.tipo is tipo for r in activas):
                raise GuardaIncumplidaError("RN6", f"Falta reservar un equipo concreto de tipo {tipo.name}.")
        for r in activas:
            r.equipo.verificar_reservable(self.franja, self._ignoradas())

    def validar_programacion(self, ahora: datetime) -> None:
        """RN7, RN2, RN4, RN3, RN5, RN6 y RN1 (sin modificar estado)."""
        if self.solicitud.cirugia not in (None, self):
            raise GuardaIncumplidaError("RN7", "La solicitud ya originó otra cirugía.")
        self._validar_rn2()
        principal = self.cirujano_principal()
        assert principal is not None
        self._validar_habilitacion(principal)
        for a in self.asignaciones.values():
            self._validar_rn3(a.profesional)
        self._validar_rn5(ahora)
        self._validar_rn6()
        self.quirofano.verificar_disponibilidad(self.franja, self.solicitud.procedimiento.nivel_contaminacion, self._ignoradas())

    # ---------------------------------------------------------- datos clínicos
    def registrar_consentimiento(self, consentimiento: ConsentimientoInformado) -> None:
        self.consentimiento = consentimiento

    def registrar_evaluacion_preanestesica(self, evaluacion: EvaluacionPreanestesica, actor: Usuario) -> None:
        if actor is not self.anestesiologo():
            raise PermisoDenegadoError("Solo el anestesiólogo de la cirugía registra la evaluación preanestésica.")
        self.evaluacion_preanestesica = evaluacion

    def registrar_justificacion_emergencia(self, justificacion: JustificacionEmergencia) -> None:
        if justificacion.firmante is not self.cirujano_principal():
            raise GuardaIncumplidaError("RN8", "La justificación debe firmarla el cirujano principal.")
        self.justificacion_emergencia = justificacion

    def consentimiento_en_plazo(self) -> bool:
        if self.limite_consentimiento is None or self.consentimiento is None:
            return False
        return self.consentimiento.fecha_firma <= self.limite_consentimiento

    def registrar_informe_operatorio(self, informe: InformeOperatorio) -> None:
        self.informe_operatorio = informe

    def registrar_aldrete(self, puntos: int) -> None:
        self.puntuacion_aldrete = puntos

    def registrar_consumo(self, insumo: Insumo, cantidad: int, ahora: datetime) -> ConsumoInsumo:
        if self.estado is not EstadoCirugia.EN_CURSO:
            raise GuardaIncumplidaError("RN14", "Los insumos solo se consumen con la cirugía EN_CURSO.")
        consumo = ConsumoInsumo(self, insumo, cantidad, ahora)
        self.consumos.append(consumo)
        return consumo

    def registrar_incidente_instrumental(self, descripcion: str) -> IncidenteInstrumental:
        inc = IncidenteInstrumental(descripcion)
        self.incidentes.append(inc)
        return inc

    def resolver_control_radiologico(self, incidente: IncidenteInstrumental) -> None:
        incidente.control_radiologico_resuelto = True

    # ---------------------------------------------------------- eventos públicos (máquina de estados)
    def programar(self, actor: Coordinador, ahora: datetime, version_quirofano: int | None = None) -> None:
        self._ejecutar("programar", actor, ahora, version_quirofano=version_quirofano)

    def confirmar(self, actor: Coordinador, ahora: datetime) -> None:
        self._ejecutar("confirmar", actor, ahora)

    def posponer(self, actor: Coordinador, ahora: datetime, motivo: str | None = None) -> None:
        self._ejecutar("posponer", actor, ahora, motivo)

    def reprogramar(self, actor: Coordinador, ahora: datetime, quirofano: Quirofano | None = None, franja: FranjaHoraria | None = None) -> None:
        anterior = (self.quirofano, self.franja)
        self.quirofano = quirofano or self.quirofano
        self.franja = franja or self.franja
        try:
            self._ejecutar("reprogramar", actor, ahora)
        except Exception:
            self.quirofano, self.franja = anterior
            raise

    def cancelar(self, actor: Coordinador, ahora: datetime, motivo: MotivoCancelacion) -> None:
        self._ejecutar("cancelar", actor, ahora, motivo_cancelacion=motivo, _origen=self.estado)

    def desplazar_por_emergencia(self, actor: Coordinador, emergencia: Cirugia, ahora: datetime) -> None:
        self._ejecutar("desplazar_por_emergencia", actor, ahora, emergencia=emergencia)

    def vencer_confirmacion(self, ahora: datetime) -> None:
        """Evento de tiempo after(45 min): lo dispara el Sistema."""
        self._ejecutar("vencer_confirmacion", None, ahora)

    def verificar_vencimiento(self, ahora: datetime) -> bool:
        if self.estado is EstadoCirugia.CONFIRMADA and ahora > self.franja.inicio + timedelta(minutes=MINUTOS_VENCIMIENTO_CONFIRMACION):
            self.vencer_confirmacion(ahora)
            return True
        return False

    def iniciar(self, actor: Cirujano, ahora: datetime) -> None:
        self._ejecutar("iniciar", actor, ahora)

    def interrumpir(self, actor: Cirujano, ahora: datetime, motivo: str | None = None) -> None:
        self._ejecutar("interrumpir", actor, ahora, motivo)

    def reanudar(self, actor: Cirujano, ahora: datetime) -> None:
        self._ejecutar("reanudar", actor, ahora)

    def finalizar_procedimiento(self, actor: Cirujano, ahora: datetime) -> None:
        self._ejecutar("finalizar_procedimiento", actor, ahora)

    def abortar(self, actor: Cirujano, ahora: datetime, motivo: str) -> None:
        self._ejecutar("abortar", actor, ahora, motivo)

    def dar_alta(self, actor: Cirujano, ahora: datetime) -> None:
        self._ejecutar("dar_alta", actor, ahora)

    # --- internas de EN_CURSO
    def pasar_a_procedimiento(self, actor: Cirujano, ahora: datetime) -> None:
        self._ejecutar_interna("pasar_a_procedimiento", actor, ahora)

    def entrar_cierre(self, actor: Cirujano, ahora: datetime) -> None:
        self._ejecutar_interna("entrar_cierre", actor, ahora)

    def registrar_conteo_inicial(self, actor: Enfermero, ahora: datetime, total_contado: int) -> None:
        self._ejecutar_interna("registrar_conteo_inicial", actor, ahora, total_contado=total_contado)

    def registrar_conteo_final(self, actor: Enfermero, ahora: datetime, total_contado: int) -> None:
        """Acción interna (sin cambio de subestado): guarda el conteo final."""
        if self.estado is not EstadoCirugia.EN_CURSO or self.conteo_inicial is None:
            raise GuardaIncumplidaError("RN11", "El conteo final requiere EN_CURSO y un conteo inicial registrado.")
        self._verificar_actor(ActorAutorizado.ENFERMERO_CIRCULANTE, actor)
        self.conteo_final = ConteoInstrumental(
            TipoConteo.FINAL, total_contado, self.conteo_inicial.total_contado, actor, ahora  # type: ignore[arg-type]
        )

    def verificar_conteo_final(self, actor: Enfermero, ahora: datetime) -> None:
        self._ejecutar_interna("verificar_conteo_final", actor, ahora)

    # ---------------------------------------------------------- motor
    def _verificar_actor(self, requerido: ActorAutorizado, actor: Usuario | None) -> None:
        if requerido is ActorAutorizado.SISTEMA:
            if actor is not None:
                raise PermisoDenegadoError("Este evento solo lo dispara el sistema (temporizador).")
            return
        if actor is None or not actor.activo:
            raise PermisoDenegadoError("Se requiere un usuario activo.")
        if requerido is ActorAutorizado.COORDINADOR:
            ok = isinstance(actor, Coordinador)
        elif requerido is ActorAutorizado.CIRUJANO_PRINCIPAL:
            ok = actor is self.cirujano_principal()
        else:
            ok = actor is self.enfermero_circulante()
        if not ok:
            raise PermisoDenegadoError(f"{actor.nombre} ({actor.rol_sistema()}) no está autorizado para este evento (requiere {requerido.name}).")

    def _ejecutar(self, evento: str, actor: Usuario | None, ahora: datetime, motivo: str | None = None, **datos: Any) -> None:
        t = TRANSICIONES.get((self.estado, evento))
        if t is None:
            regla, msg = _PROHIBIDAS.get((self.estado, evento), ("RN10", None))  # type: ignore[assignment]
            raise TransicionInvalidaError(self.estado, evento, msg, regla)
        ctx = Contexto(actor, ahora, motivo, dict(datos))
        self._verificar_actor(t.actor, actor)
        for guarda in t.guardas:
            guarda(self, ctx)
        origen = self.estado
        self.estado = t.destino
        for efecto in t.efectos:
            efecto(self, ctx)
        self._auditar(origen, t.destino, evento, ctx, notificar=True)
        self.version += 1

    def _ejecutar_interna(self, evento: str, actor: Usuario | None, ahora: datetime, **datos: Any) -> None:
        t = TRANSICIONES_INTERNAS[evento]
        if self.estado is not EstadoCirugia.EN_CURSO:
            raise TransicionInvalidaError(self.estado, evento, f"'{evento}' solo es válido con la cirugía EN_CURSO.", "RN11")
        actual = getattr(self, t.region)
        if actual is not t.origen:
            raise TransicionInvalidaError(
                self.estado, evento, f"'{evento}' requiere {t.region}={t.origen.name}, pero está en {actual.name if actual else None}.", "RN11"
            )
        ctx = Contexto(actor, ahora, None, dict(datos))
        self._verificar_actor(t.actor, actor)
        for guarda in t.guardas:
            guarda(self, ctx)
        setattr(self, t.region, t.destino)
        if evento == "registrar_conteo_inicial":
            self.conteo_inicial = ConteoInstrumental(
                TipoConteo.INICIAL, datos["total_contado"], datos["total_contado"], actor, ahora  # type: ignore[arg-type]
            )
        ctx.motivo = f"{t.region}: {t.origen.name} -> {t.destino.name}"
        self._auditar(EstadoCirugia.EN_CURSO, EstadoCirugia.EN_CURSO, evento, ctx, notificar=False)
        self.version += 1

    def _cerrar_tramo(self, ahora: datetime) -> None:
        if self._inicio_tramo is not None:
            self.minutos_reales += ceil((ahora - self._inicio_tramo).total_seconds() / 60)
            self._inicio_tramo = None

    def _destinatarios(self) -> list[str]:
        nombres = [self.solicitud.paciente.nombre]
        if (p := self.cirujano_principal()) is not None:
            nombres.append(p.nombre)
        nombres.append(self.coordinador.nombre)
        return nombres

    def _auditar(self, origen: EstadoCirugia | None, destino: EstadoCirugia, evento: str, ctx: Contexto, notificar: bool) -> None:
        ev = EventoAuditoria(self.id, origen, destino, ctx.ahora, ctx.actor.identificacion if ctx.actor else "SISTEMA", ctx.motivo, evento)
        self.eventos.append(ev)
        if notificar:
            for canal in self.canales:
                try:
                    canal.notificar(ev, self._destinatarios())
                except Exception as exc:  # un canal caído no revierte la transición (Observer)
                    self.fallos_notificacion.append((canal, exc))
