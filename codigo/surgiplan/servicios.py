"""ServicioProgramacion (fachada/controlador GRASP) y PoliticaDesplazamiento (servicio de dominio, RN9)."""
from __future__ import annotations

from datetime import datetime
from typing import Collection, Sequence

from .cirugia import Cirugia
from .dominio import CatalogoTarifas, EquipoMedico, Hospital, JustificacionEmergencia, Quirofano, SolicitudCirugia
from .enums import RolEquipo, TipoCirugia
from .excepciones import GuardaIncumplidaError, SinQuirofanoDisponibleError
from .politicas import CanalNotificacion
from .usuarios import Coordinador, PersonalClinico
from .valores import FranjaHoraria


class PoliticaDesplazamiento:
    """RN9: menor ASA y, a igualdad, inicio más tardío. Alta cohesión: solo decide a quién."""

    def seleccionar(self, candidatas: Sequence[Cirugia]) -> Cirugia | None:
        if not candidatas:
            return None
        return min(candidatas, key=lambda c: (c.solicitud.paciente.asa, -c.franja.inicio.timestamp()))


class ServicioProgramacion:
    def __init__(self, politica: PoliticaDesplazamiento | None = None) -> None:
        self.politica = politica or PoliticaDesplazamiento()
        self._secuencia = 0
        self._resultados: dict[str, Cirugia] = {}  # claves de idempotencia (Parte G-17)

    def _nuevo_id(self) -> str:
        self._secuencia += 1
        return f"C-{self._secuencia:04d}"

    def programar_cirugia(
        self,
        coordinador: Coordinador,
        solicitud: SolicitudCirugia,
        quirofano: Quirofano,
        franja: FranjaHoraria,
        equipo_quirurgico: Sequence[tuple[PersonalClinico, RolEquipo]],
        equipos: Sequence[EquipoMedico],
        ahora: datetime,
        catalogo: CatalogoTarifas,
        canales: Collection[CanalNotificacion] = (),
        version_quirofano: int | None = None,
    ) -> Cirugia:
        if not solicitud.esta_pendiente():
            raise GuardaIncumplidaError("RN7", f"La solicitud {solicitud.id} no está pendiente.")
        cirugia = Cirugia(self._nuevo_id(), solicitud, quirofano, franja, coordinador, catalogo, canales)
        for profesional, rol in equipo_quirurgico:
            cirugia.asignar_profesional(profesional, rol)
        for equipo in equipos:
            cirugia.reservar_equipo(equipo)
        cirugia.programar(coordinador, ahora, version_quirofano)
        return cirugia

    def programar_emergencia(
        self,
        coordinador: Coordinador,
        solicitud: SolicitudCirugia,
        hospital: Hospital,
        franja: FranjaHoraria,
        equipo_quirurgico: Sequence[tuple[PersonalClinico, RolEquipo]],
        equipos: Sequence[EquipoMedico],
        justificacion: JustificacionEmergencia,
        ahora: datetime,
        catalogo: CatalogoTarifas,
        canales: Collection[CanalNotificacion] = (),
        clave_idempotencia: str | None = None,
    ) -> Cirugia:
        if clave_idempotencia is not None and clave_idempotencia in self._resultados:
            return self._resultados[clave_idempotencia]  # reintento de red: mismo resultado, sin efectos
        if solicitud.tipo is not TipoCirugia.EMERGENCIA:
            raise GuardaIncumplidaError("RN9", "programar_emergencia exige una solicitud de tipo EMERGENCIA.")
        proc = solicitud.procedimiento
        quirofano = hospital.buscar_quirofano_disponible(proc, franja)
        candidata: Cirugia | None = None
        if quirofano is None:
            candidata = self.politica.seleccionar(hospital.candidatas_a_desplazar(proc, franja))
            if candidata is None:
                raise SinQuirofanoDisponibleError("RN9", "No hay quirófano compatible disponible ni cirugía electiva desplazable.")
            quirofano = candidata.quirofano
        emergencia = Cirugia(self._nuevo_id(), solicitud, quirofano, franja, coordinador, catalogo, canales)
        emergencia.marcar_candidata_a_desplazar(candidata)
        for profesional, rol in equipo_quirurgico:
            emergencia.asignar_profesional(profesional, rol)  # RN3 considera liberada a la candidata
        for equipo in equipos:
            emergencia.reservar_equipo(equipo)
        emergencia.registrar_justificacion_emergencia(justificacion)
        emergencia.validar_programacion(ahora)  # ensayo previo: si falla, no se desplaza a nadie
        if candidata is not None:
            candidata.desplazar_por_emergencia(coordinador, emergencia, ahora)
        emergencia.programar(coordinador, ahora)
        emergencia.confirmar(coordinador, ahora)  # RN8 sustitutivo (justificación firmada)
        if clave_idempotencia is not None:
            self._resultados[clave_idempotencia] = emergencia
        return emergencia
