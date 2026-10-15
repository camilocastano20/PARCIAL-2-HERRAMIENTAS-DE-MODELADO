"""
Maintenance Pro

"""
from __future__ import annotations

import itertools
from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal
from enum import Enum


# ======================================================================
# Enumeraciones (estados y prioridades)
# ======================================================================
class EstadoEquipo(Enum):
    OPERATIVO = "OPERATIVO"
    EN_MANTENIMIENTO = "EN_MANTENIMIENTO"
    FUERA_DE_SERVICIO = "FUERA_DE_SERVICIO"


class EstadoOrden(Enum):
    CREADA = "CREADA"
    PROGRAMADA = "PROGRAMADA"
    EN_EJECUCION = "EN_EJECUCION"
    SUSPENDIDA = "SUSPENDIDA"
    FINALIZADA = "FINALIZADA"
    CANCELADA = "CANCELADA"


class Prioridad(Enum):
    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"
    CRITICA = "CRITICA"  # "CRÍTICA" en el enunciado (sin tilde en el identificador)


# Estados finales posibles del equipo cuando termina el mantenimiento (decide el supervisor)
_DESTINOS_EQUIPO = frozenset({EstadoEquipo.OPERATIVO, EstadoEquipo.FUERA_DE_SERVICIO})


# ======================================================================
# Excepciones propias
# ======================================================================
class ReglaNegocioError(Exception):
    """Base de todas las violaciones de reglas de negocio de Maintenance Pro."""


class TransicionInvalidaError(ReglaNegocioError):
    """RN5: transición de estado no permitida."""


class PermisoError(ReglaNegocioError):
    """RN1: solo el técnico responsable puede iniciar, suspender y finalizar."""


class ReporteYaTieneOrdenError(ReglaNegocioError):
    """RN3: un reporte origina como máximo una orden."""


class ConflictoAgendaError(ReglaNegocioError):
    """RN2: el técnico ya es responsable de otra orden programada ese día."""


class OrdenSinActividadesError(ReglaNegocioError):
    """RN6: no se puede finalizar una orden sin actividades registradas."""


class HorasTrabajadasInvalidasError(ReglaNegocioError):
    """RN6: las horas trabajadas totales deben ser mayores que cero."""


class EntidadNoEncontradaError(ReglaNegocioError):
    """No existe la entidad solicitada (reporte, orden o técnico)."""


# ======================================================================
# Servicios externos (abstracciones que permiten extender sin modificar el dominio)
# ======================================================================
class ServicioExterno(ABC):
    @abstractmethod
    def nombre(self) -> str: ...

    @abstractmethod
    def esta_disponible(self) -> bool: ...


class Notificador(ServicioExterno):
    @abstractmethod
    def notificar(self, destinatario: Usuario, mensaje: str) -> bool: ...


class ProveedorRepuestos(ServicioExterno):
    @abstractmethod
    def consultar_stock(self, repuesto: Repuesto, cantidad: int) -> bool: ...


class NotificadorCorreo(Notificador):
    def __init__(self, servidor_smtp: str = "smtp.maintenancepro.local") -> None:
        self._servidor_smtp = servidor_smtp

    def nombre(self) -> str:
        return "Notificador por correo"

    def esta_disponible(self) -> bool:
        return True

    def notificar(self, destinatario: Usuario, mensaje: str) -> bool:
        print(f"   [correo vía {self._servidor_smtp}] Para {destinatario.correo}: {mensaje}")
        return True


class ProveedorRepuestosHttp(ProveedorRepuestos):
    def __init__(self, url_base: str = "https://proveedor.example/api") -> None:
        self._url_base = url_base

    def nombre(self) -> str:
        return "Proveedor de repuestos (HTTP)"

    def esta_disponible(self) -> bool:
        return True

    def consultar_stock(self, repuesto: Repuesto, cantidad: int) -> bool:
        return cantidad > 0  # simulado: una integración real consultaría self._url_base


# ======================================================================
# Equipo
# ======================================================================
class Equipo:
    def __init__(
        self,
        codigo_interno: str,
        tipo: str,
        marca: str,
        modelo: str,
        fecha_adquisicion: date,
        estado: EstadoEquipo = EstadoEquipo.OPERATIVO,
    ) -> None:
        self._codigo_interno = codigo_interno
        self._tipo = tipo
        self._marca = marca
        self._modelo = modelo
        self._fecha_adquisicion = fecha_adquisicion
        self._estado = estado

    @property
    def codigo_interno(self) -> str:
        return self._codigo_interno

    @property
    def tipo(self) -> str:
        return self._tipo

    @property
    def marca(self) -> str:
        return self._marca

    @property
    def modelo(self) -> str:
        return self._modelo

    @property
    def fecha_adquisicion(self) -> date:
        return self._fecha_adquisicion

    @property
    def estado(self) -> EstadoEquipo:
        return self._estado

    def poner_en_mantenimiento(self) -> None:
        """Efecto de EN_EJECUCION sobre el equipo (el equipo pasa a EN_MANTENIMIENTO)."""
        self._estado = EstadoEquipo.EN_MANTENIMIENTO

    def finalizar_mantenimiento(self, destino: EstadoEquipo) -> None:
        """El supervisor decide si el equipo vuelve a OPERATIVO o pasa a FUERA_DE_SERVICIO."""
        if self._estado is not EstadoEquipo.EN_MANTENIMIENTO:
            raise ReglaNegocioError(
                f"El equipo {self._codigo_interno} está {self._estado.value}; "
                "solo un equipo EN_MANTENIMIENTO puede cerrar su mantenimiento."
            )
        if destino not in _DESTINOS_EQUIPO:
            raise ReglaNegocioError(
                f"Estado destino inválido para el equipo: {destino.value}. "
                "Debe ser OPERATIVO o FUERA_DE_SERVICIO."
            )
        self._estado = destino

    def esta_operativo(self) -> bool:
        return self._estado is EstadoEquipo.OPERATIVO

    def __repr__(self) -> str:
        return f"Equipo({self._codigo_interno!r}, {self._tipo}, estado={self._estado.value})"


# ======================================================================
# Usuarios (generalización)
# ======================================================================
class Usuario(ABC):
    def __init__(self, id_usuario: int, nombre: str, correo: str) -> None:
        self._id_usuario = id_usuario
        self._nombre = nombre
        self._correo = correo

    @property
    def id_usuario(self) -> int:
        return self._id_usuario

    @property
    def nombre(self) -> str:
        return self._nombre

    @property
    def correo(self) -> str:
        return self._correo

    @abstractmethod
    def obtener_rol(self) -> str: ...

    def __repr__(self) -> str:
        return f"{self.obtener_rol()}({self._nombre})"


class Operador(Usuario):
    def obtener_rol(self) -> str:
        return "Operador"

    def reportar_falla(
        self, equipo: Equipo, descripcion: str, prioridad: Prioridad, fecha: date | None = None
    ) -> ReporteFalla:
        return ReporteFalla(descripcion, prioridad, equipo, self, fecha)


class Supervisor(Usuario):
    def obtener_rol(self) -> str:
        return "Supervisor"

    def revisar_reporte(self, reporte: ReporteFalla) -> bool:
        """Un reporte procede a orden solo si aún no originó ninguna (RN3)."""
        return not reporte.tiene_orden()

    def cancelar_orden(
        self, orden: OrdenMantenimiento, destino_equipo: EstadoEquipo | None = None
    ) -> None:
        orden.cancelar(destino_equipo)


class Tecnico(Usuario):
    def __init__(self, id_usuario: int, nombre: str, correo: str, especialidad: str) -> None:
        super().__init__(id_usuario, nombre, correo)
        self._especialidad = especialidad
        self._ordenes_responsable: list[OrdenMantenimiento] = []

    @property
    def especialidad(self) -> str:
        return self._especialidad

    def obtener_rol(self) -> str:
        return "Tecnico"

    def registrar_orden(self, orden: OrdenMantenimiento) -> None:
        if orden not in self._ordenes_responsable:
            self._ordenes_responsable.append(orden)

    def retirar_orden(self, orden: OrdenMantenimiento) -> None:
        if orden in self._ordenes_responsable:
            self._ordenes_responsable.remove(orden)

    def orden_programada_en(self, fecha: date) -> OrdenMantenimiento | None:
        """RN2: devuelve la orden (de la que es responsable) programada para esa fecha, si existe.
        Cuentan solo las órdenes vigentes: PROGRAMADA, EN_EJECUCION o SUSPENDIDA."""
        vigentes = (EstadoOrden.PROGRAMADA, EstadoOrden.EN_EJECUCION, EstadoOrden.SUSPENDIDA)
        for orden in self._ordenes_responsable:
            if orden.fecha_programada == fecha and orden.estado in vigentes:
                return orden
        return None

    def esta_disponible(self, fecha: date) -> bool:
        return self.orden_programada_en(fecha) is None


# ======================================================================
# Repuestos
# ======================================================================
class Repuesto:
    """Elemento del catálogo (RN8)."""

    def __init__(self, codigo: str, nombre: str, costo_referencia: Decimal) -> None:
        self._codigo = codigo
        self._nombre = nombre
        self._costo_referencia = costo_referencia

    @property
    def codigo(self) -> str:
        return self._codigo

    @property
    def nombre(self) -> str:
        return self._nombre

    @property
    def costo_referencia(self) -> Decimal:
        return self._costo_referencia

    def actualizar_costo_referencia(self, nuevo: Decimal) -> None:
        if nuevo < 0:
            raise ReglaNegocioError("El costo de referencia no puede ser negativo.")
        self._costo_referencia = nuevo


class RepuestoUtilizado:
    """Uso concreto de un repuesto: guarda el costo vigente al usarlo (RN8)."""

    def __init__(self, repuesto: Repuesto, cantidad: int, costo_unitario: Decimal) -> None:
        if cantidad <= 0:
            raise ReglaNegocioError("La cantidad de repuestos utilizados debe ser mayor que cero.")
        self._repuesto = repuesto
        self._cantidad = cantidad
        self._costo_unitario = costo_unitario

    @property
    def repuesto(self) -> Repuesto:
        return self._repuesto

    @property
    def cantidad(self) -> int:
        return self._cantidad

    @property
    def costo_unitario(self) -> Decimal:
        return self._costo_unitario

    def subtotal(self) -> Decimal:
        return self._cantidad * self._costo_unitario


# ======================================================================
# Actividad
# ======================================================================
class Actividad:
    def __init__(
        self,
        descripcion: str,
        horas_trabajadas: float,
        tecnico: Tecnico,
        fecha: date | None = None,
    ) -> None:
        if not descripcion.strip():
            raise ReglaNegocioError("La actividad debe tener una descripción.")
        if horas_trabajadas <= 0:
            raise HorasTrabajadasInvalidasError(
                f"Las horas trabajadas de una actividad deben ser mayores que cero (recibido: {horas_trabajadas})."
            )
        self._descripcion = descripcion
        self._horas_trabajadas = horas_trabajadas
        self._tecnico = tecnico
        self._fecha = fecha or date.today()

    @property
    def descripcion(self) -> str:
        return self._descripcion

    @property
    def horas_trabajadas(self) -> float:
        return self._horas_trabajadas

    @property
    def fecha(self) -> date:
        return self._fecha

    @property
    def tecnico(self) -> Tecnico:
        return self._tecnico

    def es_valida(self) -> bool:
        return bool(self._descripcion.strip()) and self._horas_trabajadas > 0

    def resumen(self) -> str:
        return f"{self._descripcion} ({self._horas_trabajadas} h, {self._tecnico.nombre})"

    def __repr__(self) -> str:
        return f"Actividad({self.resumen()})"


# ======================================================================
# ReporteFalla
# ======================================================================
class ReporteFalla:
    _secuencia = itertools.count(1)

    def __init__(
        self,
        descripcion: str,
        prioridad: Prioridad,
        equipo: Equipo,
        operador: Operador,
        fecha: date | None = None,
        id_reporte: int | None = None,
    ) -> None:
        self._id_reporte = id_reporte if id_reporte is not None else next(ReporteFalla._secuencia)
        self._fecha = fecha or date.today()
        self._descripcion = descripcion
        self._prioridad = prioridad
        self._equipo = equipo
        self._operador = operador
        self._orden: OrdenMantenimiento | None = None  # multiplicidad 0..1 (RN3)

    @property
    def id_reporte(self) -> int:
        return self._id_reporte

    @property
    def fecha(self) -> date:
        return self._fecha

    @property
    def descripcion(self) -> str:
        return self._descripcion

    @property
    def prioridad(self) -> Prioridad:
        return self._prioridad

    @property
    def equipo(self) -> Equipo:
        return self._equipo

    @property
    def operador(self) -> Operador:
        return self._operador

    def tiene_orden(self) -> bool:
        return self._orden is not None

    def asociar_orden(self, orden: OrdenMantenimiento) -> None:
        """RN3: un reporte puede originar como máximo una orden."""
        if self._orden is not None:
            raise ReporteYaTieneOrdenError(
                f"El reporte {self._id_reporte} ya originó la orden N° {self._orden.numero} (RN3)."
            )
        self._orden = orden


# ======================================================================
# OrdenMantenimiento
# ======================================================================
class OrdenMantenimiento:
    # RN5: transiciones permitidas. FINALIZADA y CANCELADA son estados finales.
    _TRANSICIONES: dict[EstadoOrden, frozenset[EstadoOrden]] = {
        EstadoOrden.CREADA: frozenset({EstadoOrden.PROGRAMADA, EstadoOrden.CANCELADA}),
        EstadoOrden.PROGRAMADA: frozenset({EstadoOrden.EN_EJECUCION, EstadoOrden.CANCELADA}),
        EstadoOrden.EN_EJECUCION: frozenset({EstadoOrden.SUSPENDIDA, EstadoOrden.FINALIZADA}),
        EstadoOrden.SUSPENDIDA: frozenset({EstadoOrden.EN_EJECUCION, EstadoOrden.CANCELADA}),
        EstadoOrden.FINALIZADA: frozenset(),
        EstadoOrden.CANCELADA: frozenset(),
    }
    _ESTADOS_DE_TRABAJO = (EstadoOrden.EN_EJECUCION, EstadoOrden.SUSPENDIDA)

    def __init__(
        self,
        numero: int,
        descripcion: str,
        prioridad: Prioridad,
        reporte: ReporteFalla,
        supervisor: Supervisor | None = None,
        fecha_creacion: date | None = None,
    ) -> None:
        self._numero = numero
        self._fecha_creacion = fecha_creacion or date.today()
        self._descripcion = descripcion
        self._prioridad = prioridad
        self._estado = EstadoOrden.CREADA  # estado inicial de la máquina de estados
        self._fecha_programada: date | None = None
        self._reporte = reporte
        self._supervisor = supervisor
        self._responsable: Tecnico | None = None  # RN1
        self._tecnicos_apoyo: list[Tecnico] = []  # RN1: cero o más
        self._actividades: list[Actividad] = []  # composición
        self._repuestos_utilizados: list[RepuestoUtilizado] = []  # composición
        reporte.asociar_orden(self)  # RN3: lanza ReporteYaTieneOrdenError si ya tenía orden

    # ---------------- propiedades ----------------
    @property
    def numero(self) -> int:
        return self._numero

    @property
    def fecha_creacion(self) -> date:
        return self._fecha_creacion

    @property
    def descripcion(self) -> str:
        return self._descripcion

    @property
    def prioridad(self) -> Prioridad:
        return self._prioridad

    @property
    def estado(self) -> EstadoOrden:
        return self._estado

    @property
    def fecha_programada(self) -> date | None:
        return self._fecha_programada

    @property
    def responsable(self) -> Tecnico | None:
        return self._responsable

    @property
    def tecnicos_apoyo(self) -> tuple[Tecnico, ...]:
        return tuple(self._tecnicos_apoyo)

    @property
    def actividades(self) -> tuple[Actividad, ...]:
        return tuple(self._actividades)

    @property
    def repuestos_utilizados(self) -> tuple[RepuestoUtilizado, ...]:
        return tuple(self._repuestos_utilizados)

    @property
    def equipo(self) -> Equipo:  # atributo derivado "/equipo"
        return self._reporte.equipo

    # ---------------- máquina de estados (RN5) ----------------
    def _validar_transicion(self, nuevo: EstadoOrden) -> None:
        if nuevo not in self._TRANSICIONES[self._estado]:
            detalle = ""
            if self._estado in (EstadoOrden.FINALIZADA, EstadoOrden.CANCELADA):
                detalle = f" {self._estado.value} es un estado final."
            elif self._estado is EstadoOrden.EN_EJECUCION and nuevo is EstadoOrden.CANCELADA:
                detalle = " Una orden EN_EJECUCION no puede cancelarse."
            raise TransicionInvalidaError(
                f"Orden {self._numero}: transición no permitida "
                f"{self._estado.value} -> {nuevo.value} (RN5).{detalle}"
            )

    def _transicionar(self, nuevo: EstadoOrden) -> None:
        self._validar_transicion(nuevo)
        self._estado = nuevo

    def _exigir_responsable(self, solicitante: Tecnico) -> None:
        """RN1: solo el técnico responsable puede iniciar, suspender, reanudar y finalizar."""
        if self._responsable is None or solicitante is not self._responsable:
            raise PermisoError(
                f"Orden {self._numero}: solo el técnico responsable puede realizar esta acción (RN1)."
            )

    # ---------------- asignación y programación ----------------
    def asignar_responsable(self, tecnico: Tecnico) -> None:
        """RN1: exactamente un responsable (se puede reasignar mientras la orden esté CREADA)."""
        if self._estado is not EstadoOrden.CREADA:
            raise ReglaNegocioError(
                f"Orden {self._numero}: el responsable solo puede asignarse en estado CREADA."
            )
        if tecnico in self._tecnicos_apoyo:
            raise ReglaNegocioError("El técnico ya es de apoyo en esta orden; no puede ser responsable.")
        if self._responsable is not None and self._responsable is not tecnico:
            self._responsable.retirar_orden(self)
        self._responsable = tecnico
        tecnico.registrar_orden(self)

    def agregar_apoyo(self, tecnico: Tecnico) -> None:
        if self._estado in (EstadoOrden.FINALIZADA, EstadoOrden.CANCELADA):
            raise ReglaNegocioError(f"Orden {self._numero}: está {self._estado.value}, no admite cambios.")
        if tecnico is self._responsable or tecnico in self._tecnicos_apoyo:
            raise ReglaNegocioError("El técnico ya participa en esta orden.")
        self._tecnicos_apoyo.append(tecnico)

    def programar(self, fecha: date) -> None:
        """CREADA -> PROGRAMADA. Valida RN4 (responsable y fecha) y RN2 (agenda del técnico)."""
        self._validar_transicion(EstadoOrden.PROGRAMADA)
        if self._responsable is None:
            raise ReglaNegocioError(
                f"Orden {self._numero}: no se puede programar sin técnico responsable (RN4)."
            )
        if fecha < self._fecha_creacion:
            raise ReglaNegocioError(
                f"Orden {self._numero}: la fecha programada ({fecha}) no puede ser anterior "
                f"a la fecha de creación ({self._fecha_creacion}) (RN4)."
            )
        conflicto = self._responsable.orden_programada_en(fecha)  # RN2: lo verifica el Tecnico
        if conflicto is not None:
            raise ConflictoAgendaError(
                f"{self._responsable.nombre} ya es responsable de la orden N° {conflicto.numero}, "
                f"programada para el {fecha} (RN2)."
            )
        self._fecha_programada = fecha
        self._transicionar(EstadoOrden.PROGRAMADA)

    # ---------------- ejecución ----------------
    def iniciar(self, solicitante: Tecnico) -> None:
        """PROGRAMADA -> EN_EJECUCION; el equipo pasa a EN_MANTENIMIENTO."""
        self._validar_transicion(EstadoOrden.EN_EJECUCION)
        self._exigir_responsable(solicitante)
        self._transicionar(EstadoOrden.EN_EJECUCION)
        self.equipo.poner_en_mantenimiento()

    def suspender(self, solicitante: Tecnico) -> None:
        """EN_EJECUCION -> SUSPENDIDA; el equipo permanece EN_MANTENIMIENTO (RN7)."""
        self._validar_transicion(EstadoOrden.SUSPENDIDA)
        self._exigir_responsable(solicitante)
        self._transicionar(EstadoOrden.SUSPENDIDA)

    def reanudar(self, solicitante: Tecnico) -> None:
        """SUSPENDIDA -> EN_EJECUCION; el equipo ya está EN_MANTENIMIENTO."""
        self._validar_transicion(EstadoOrden.EN_EJECUCION)
        self._exigir_responsable(solicitante)
        self._transicionar(EstadoOrden.EN_EJECUCION)

    def finalizar(self, solicitante: Tecnico, destino_equipo: EstadoEquipo) -> None:
        """EN_EJECUCION -> FINALIZADA. RN6: requiere >= 1 actividad y horas totales > 0.
        destino_equipo es la decisión del supervisor (OPERATIVO o FUERA_DE_SERVICIO)."""
        self._validar_transicion(EstadoOrden.FINALIZADA)
        self._exigir_responsable(solicitante)
        if not self._actividades:
            raise OrdenSinActividadesError(
                f"No se puede finalizar la orden N° {self._numero}: "
                "no tiene actividades registradas (RN6)."
            )
        if self.horas_totales() <= 0:
            raise HorasTrabajadasInvalidasError(
                f"No se puede finalizar la orden N° {self._numero}: "
                "las horas trabajadas totales deben ser mayores que cero (RN6)."
            )
        self.equipo.finalizar_mantenimiento(destino_equipo)  # puede lanzar; la orden aún no cambió
        self._transicionar(EstadoOrden.FINALIZADA)

    def cancelar(self, destino_equipo: EstadoEquipo | None = None) -> None:
        """CREADA/PROGRAMADA/SUSPENDIDA -> CANCELADA (RN5).
        Si nunca estuvo en ejecución, el equipo no cambia (RN7). Si estaba SUSPENDIDA el equipo
        está EN_MANTENIMIENTO y el supervisor debe indicar su destino (asunción A3)."""
        self._validar_transicion(EstadoOrden.CANCELADA)
        if self._estado is EstadoOrden.SUSPENDIDA:
            if destino_equipo is None:
                raise ReglaNegocioError(
                    f"Orden {self._numero}: para cancelar una orden SUSPENDIDA el supervisor debe "
                    "indicar el estado destino del equipo (OPERATIVO o FUERA_DE_SERVICIO)."
                )
            self.equipo.finalizar_mantenimiento(destino_equipo)
        self._transicionar(EstadoOrden.CANCELADA)

    # ---------------- registro de trabajo ----------------
    def _exigir_estado_de_trabajo(self) -> None:
        if self._estado not in self._ESTADOS_DE_TRABAJO:
            raise ReglaNegocioError(
                f"Orden {self._numero}: solo se registra trabajo en estado EN_EJECUCION o SUSPENDIDA "
                f"(estado actual: {self._estado.value})."
            )

    def registrar_actividad(self, descripcion: str, horas: float, tecnico: Tecnico) -> Actividad:
        self._exigir_estado_de_trabajo()
        if tecnico is not self._responsable and tecnico not in self._tecnicos_apoyo:
            raise PermisoError(f"{tecnico.nombre} no participa en la orden {self._numero}.")
        actividad = Actividad(descripcion, horas, tecnico)
        self._actividades.append(actividad)
        return actividad

    def agregar_repuesto(self, repuesto: Repuesto, cantidad: int) -> RepuestoUtilizado:
        """RN8: se copia el costo de referencia vigente como costo_unitario histórico."""
        self._exigir_estado_de_trabajo()
        uso = RepuestoUtilizado(repuesto, cantidad, repuesto.costo_referencia)
        self._repuestos_utilizados.append(uso)
        return uso

    def horas_totales(self) -> float:
        return sum(a.horas_trabajadas for a in self._actividades)

    def costo_total(self) -> Decimal:
        """RN9: suma de (cantidad x costo_unitario) de los repuestos utilizados."""
        return sum((r.subtotal() for r in self._repuestos_utilizados), Decimal("0"))

    def __repr__(self) -> str:
        return f"OrdenMantenimiento(N° {self._numero}, {self._estado.value})"


# ======================================================================
# Empresa y Sistema (GestorMantenimiento)
# ======================================================================
class Empresa:
    def __init__(self, nit: str, nombre: str) -> None:
        self._nit = nit
        self._nombre = nombre
        self._equipos: dict[str, Equipo] = {}  # composición 1 -> 0..*
        self._usuarios: list[Usuario] = []  # agregación 1 -> 0..*

    @property
    def nit(self) -> str:
        return self._nit

    @property
    def nombre(self) -> str:
        return self._nombre

    def agregar_equipo(self, equipo: Equipo) -> None:
        if equipo.codigo_interno in self._equipos:
            raise ReglaNegocioError(f"Ya existe un equipo con código {equipo.codigo_interno}.")
        self._equipos[equipo.codigo_interno] = equipo

    def registrar_usuario(self, usuario: Usuario) -> None:
        self._usuarios.append(usuario)

    def buscar_equipo(self, codigo_interno: str) -> Equipo:
        try:
            return self._equipos[codigo_interno]
        except KeyError:
            raise EntidadNoEncontradaError(f"No existe el equipo {codigo_interno}.") from None


class GestorMantenimiento:
    """Rol «Sistema» del diagrama de secuencia: recibe las solicitudes del supervisor."""

    def __init__(
        self,
        notificador: Notificador,
        reportes: list[ReporteFalla],
        tecnicos: list[Tecnico],
    ) -> None:
        self._notificador = notificador
        self._reportes = {r.id_reporte: r for r in reportes}
        self._tecnicos = {t.id_usuario: t for t in tecnicos}
        self._ordenes: dict[int, OrdenMantenimiento] = {}
        self._siguiente_numero = 1

    def buscar_reporte(self, id_reporte: int) -> ReporteFalla:
        if id_reporte not in self._reportes:
            raise EntidadNoEncontradaError(f"No existe el reporte {id_reporte}.")
        return self._reportes[id_reporte]

    def buscar_orden(self, numero_orden: int) -> OrdenMantenimiento:
        if numero_orden not in self._ordenes:
            raise EntidadNoEncontradaError(f"No existe la orden {numero_orden}.")
        return self._ordenes[numero_orden]

    def buscar_tecnico(self, id_tecnico: int) -> Tecnico:
        if id_tecnico not in self._tecnicos:
            raise EntidadNoEncontradaError(f"No existe el técnico {id_tecnico}.")
        return self._tecnicos[id_tecnico]

    def generar_orden(
        self, id_reporte: int, descripcion: str, supervisor: Supervisor, fecha_creacion: date | None = None
    ) -> OrdenMantenimiento:
        reporte = self.buscar_reporte(id_reporte)
        if reporte.tiene_orden():  # RN3 (fragmento alt del diagrama de secuencia)
            raise ReporteYaTieneOrdenError(f"El reporte {id_reporte} ya originó una orden (RN3).")
        orden = OrdenMantenimiento(
            self._siguiente_numero, descripcion, reporte.prioridad, reporte, supervisor, fecha_creacion
        )
        self._ordenes[orden.numero] = orden
        self._siguiente_numero += 1
        return orden

    def asignar_tecnico(self, numero_orden: int, id_tecnico: int) -> None:
        orden = self.buscar_orden(numero_orden)
        tecnico = self.buscar_tecnico(id_tecnico)
        orden.asignar_responsable(tecnico)

    def programar_orden(self, numero_orden: int, fecha: date) -> None:
        orden = self.buscar_orden(numero_orden)
        orden.programar(fecha)  # valida RN4 y RN2; lanza excepción si se viola alguna
        if self._notificador is not None and self._notificador.esta_disponible():  # fragmento opt
            self._notificador.notificar(
                orden.responsable, f"Se le asignó la orden N° {orden.numero} para el {fecha}."
            )


# ======================================================================
# Demostración (casos de la Parte E)
# ======================================================================
def _titulo(texto: str) -> None:
    print(f"\n{'=' * 70}\n{texto}\n{'=' * 70}")


def demo() -> None:
    hoy = date(2026, 10, 10)
    empresa = Empresa("900.123.456-7", "Industrias del Magdalena S.A.S.")
    compresor = Equipo("EQ-001", "Compresor", "Atlas Copco", "GA-55", date(2021, 3, 15))
    torno = Equipo("EQ-002", "Torno CNC", "Haas", "ST-20", date(2022, 8, 1))
    empresa.agregar_equipo(compresor)
    empresa.agregar_equipo(torno)

    operador = Operador(1, "Laura Gómez", "laura@empresa.co")
    supervisor = Supervisor(2, "Carlos Ruiz", "carlos@empresa.co")
    ana = Tecnico(3, "Ana Pérez", "ana@empresa.co", "Mecánica")
    for u in (operador, supervisor, ana):
        empresa.registrar_usuario(u)

    r1 = operador.reportar_falla(compresor, "Pérdida de presión", Prioridad.ALTA, hoy)
    r2 = operador.reportar_falla(torno, "Vibración anormal en el husillo", Prioridad.CRITICA, hoy)
    r3 = operador.reportar_falla(compresor, "Fuga de aceite", Prioridad.MEDIA, hoy)
    gestor = GestorMantenimiento(NotificadorCorreo(), [r1, r2, r3], [ana])
    filtro = Repuesto("REP-10", "Filtro de aire", Decimal("45000"))

    # ---------------- CASO CORRECTO ----------------
    _titulo("CASO CORRECTO: ciclo completo de la orden 1")
    o1 = gestor.generar_orden(r1.id_reporte, "Reparar pérdida de presión", supervisor, hoy)
    print(f"1. {o1} creada. Equipo: {o1.equipo.estado.value}")
    gestor.asignar_tecnico(o1.numero, ana.id_usuario)
    gestor.programar_orden(o1.numero, date(2026, 10, 12))
    print(f"2. {o1}, fecha programada: {o1.fecha_programada}")
    o1.iniciar(ana)
    print(f"3. {o1}. Equipo: {o1.equipo.estado.value}")
    o1.registrar_actividad("Cambio de filtro y ajuste de válvulas", 3.5, ana)
    o1.agregar_repuesto(filtro, 2)
    filtro.actualizar_costo_referencia(Decimal("60000"))  # el catálogo cambia después (RN8)
    print(f"4. Horas totales: {o1.horas_totales()} h | Costo total: ${o1.costo_total():,.0f} "
          "(no cambia aunque el catálogo suba, RN8)")
    o1.finalizar(ana, EstadoEquipo.OPERATIVO)
    print(f"5. {o1}. Equipo: {o1.equipo.estado.value}")

    # ---------------- CASO DE ERROR (RN6) ----------------
    _titulo("CASO DE ERROR (RN6): finalizar sin actividades registradas")
    o2 = gestor.generar_orden(r2.id_reporte, "Revisar husillo del torno", supervisor, hoy)
    gestor.asignar_tecnico(o2.numero, ana.id_usuario)
    gestor.programar_orden(o2.numero, date(2026, 10, 14))
    o2.iniciar(ana)
    print(f"{o2}. Equipo: {o2.equipo.estado.value}. Actividades registradas: {len(o2.actividades)}")
    try:
        o2.finalizar(ana, EstadoEquipo.OPERATIVO)
    except OrdenSinActividadesError as error:
        print(f"ERROR CAPTURADO [{type(error).__name__}]: {error}")
    print(f"Estado tras el error: {o2} | Equipo: {o2.equipo.estado.value} (sin cambios)")

    # ---------------- EXTRAS: otras reglas ----------------
    _titulo("EXTRA RN2: el técnico ya tiene una orden programada ese día")
    o3 = gestor.generar_orden(r3.id_reporte, "Corregir fuga de aceite", supervisor, hoy)
    gestor.asignar_tecnico(o3.numero, ana.id_usuario)
    try:
        gestor.programar_orden(o3.numero, date(2026, 10, 14))
    except ConflictoAgendaError as error:
        print(f"ERROR CAPTURADO [{type(error).__name__}]: {error}")
    print(f"{o3} (permanece CREADA)")

    _titulo("EXTRA RN5: una orden EN_EJECUCION no puede cancelarse")
    try:
        o2.cancelar()
    except TransicionInvalidaError as error:
        print(f"ERROR CAPTURADO [{type(error).__name__}]: {error}")

    _titulo("EXTRA RN3: un reporte origina como máximo una orden")
    try:
        gestor.generar_orden(r1.id_reporte, "Segunda orden del mismo reporte", supervisor, hoy)
    except ReporteYaTieneOrdenError as error:
        print(f"ERROR CAPTURADO [{type(error).__name__}]: {error}")

    _titulo("RECUPERACIÓN: se registra la actividad y la orden 2 ya puede finalizarse")
    o2.registrar_actividad("Cambio de rodamientos del husillo", 5.0, ana)
    o2.finalizar(ana, EstadoEquipo.FUERA_DE_SERVICIO)
    print(f"{o2}. Equipo: {o2.equipo.estado.value} (decisión del supervisor)")

    _titulo("EXTRA RN5: una orden CANCELADA no puede volver a PROGRAMADA")
    o3.cancelar()
    try:
        o3.programar(date(2026, 10, 20))
    except TransicionInvalidaError as error:
        print(f"ERROR CAPTURADO [{type(error).__name__}]: {error}")


if __name__ == "__main__":
    demo()