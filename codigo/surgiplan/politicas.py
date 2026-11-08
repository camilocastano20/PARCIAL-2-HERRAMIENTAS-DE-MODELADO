"""Abstracciones y patrones: Strategy (duración, plan de seguro), Observer/Adapter
(canales de notificación) y Adapter (pasarelas de pago)."""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, Sequence

from .enums import RECARGO_ASA_PORCENTAJE, UMBRAL_ASA_RECARGO

if TYPE_CHECKING:
    from .dominio import Paciente, Procedimiento
    from .valores import EventoAuditoria


# ---------------------------------------------------------------- Strategy RN5
class EstrategiaDuracion(Protocol):
    """«Strategy»: duración mínima de la franja (RN5)."""

    def minutos_minimos(self, procedimiento: Procedimiento, paciente: Paciente) -> int: ...


class DuracionEstandar(EstrategiaDuracion):
    def minutos_minimos(self, procedimiento: Procedimiento, paciente: Paciente) -> int:
        return procedimiento.duracion_estimada_min


class DuracionConRecargoAsa(EstrategiaDuracion):
    """ASA >= 3 -> +25 % (redondeo hacia arriba, ASUNCIÓN 8)."""

    def minutos_minimos(self, procedimiento: Procedimiento, paciente: Paciente) -> int:
        base = procedimiento.duracion_estimada_min
        if paciente.asa >= UMBRAL_ASA_RECARGO:
            return -(-base * (100 + RECARGO_ASA_PORCENTAJE) // 100)
        return base


# ------------------------------------------------------- Strategy: plan seguro
class PlanSeguro(Protocol):
    """«Strategy»: cada plan define su copago y su cargo por cancelación tardía."""

    nombre: str

    def calcular_copago(self, costo_total: Decimal) -> Decimal: ...

    def calcular_cargo_cancelacion_tardia(self) -> Decimal: ...


CARGO_ADMINISTRATIVO_BASE = Decimal("50000")


class PlanParticular(PlanSeguro):
    nombre = "PARTICULAR"

    def calcular_copago(self, costo_total: Decimal) -> Decimal:
        return costo_total

    def calcular_cargo_cancelacion_tardia(self) -> Decimal:
        return CARGO_ADMINISTRATIVO_BASE


class PlanEps(PlanSeguro):
    nombre = "EPS"

    def calcular_copago(self, costo_total: Decimal) -> Decimal:
        return (costo_total * Decimal("0.10")).quantize(Decimal("0.01"))

    def calcular_cargo_cancelacion_tardia(self) -> Decimal:
        return Decimal("0")


class PlanPrepagada(PlanSeguro):
    nombre = "PREPAGADA"

    def calcular_copago(self, costo_total: Decimal) -> Decimal:
        return (costo_total * Decimal("0.20")).quantize(Decimal("0.01"))

    def calcular_cargo_cancelacion_tardia(self) -> Decimal:
        return CARGO_ADMINISTRATIVO_BASE / 2


# ----------------------------------------------- Observer / Adapter: canales
class CanalNotificacion(Protocol):
    """«Observer»: cada canal se suscribe a la Cirugía (sujeto) y recibe los eventos."""

    def notificar(self, evento: EventoAuditoria, destinatarios: Sequence[str]) -> None: ...


class CanalCorreo(CanalNotificacion):
    def __init__(self) -> None:
        self.enviados: list[str] = []

    def notificar(self, evento: EventoAuditoria, destinatarios: Sequence[str]) -> None:
        for d in destinatarios:
            self.enviados.append(f"correo a {d}: {evento.evento} -> {evento.estado_destino.name}")


class CanalSms(CanalNotificacion):
    def __init__(self) -> None:
        self.enviados: list[str] = []

    def notificar(self, evento: EventoAuditoria, destinatarios: Sequence[str]) -> None:
        for d in destinatarios:
            self.enviados.append(f"sms a {d}: cirugía {evento.cirugia_id} {evento.estado_destino.name}")


class ClienteHl7Externo:
    """API ajena (no modificable) del sistema hospitalario."""

    def __init__(self) -> None:
        self.mensajes: list[str] = []

    def enviar_mensaje(self, raw: str) -> None:
        self.mensajes.append(raw)


class AdaptadorHl7(CanalNotificacion):
    """«Adapter»: traduce EventoAuditoria a un mensaje HL7 y usa el cliente externo."""

    def __init__(self, cliente: ClienteHl7Externo) -> None:
        self._cliente = cliente

    def notificar(self, evento: EventoAuditoria, destinatarios: Sequence[str]) -> None:
        raw = f"MSH|^~\\&|SURGIPLAN||HIS||{evento.momento:%Y%m%d%H%M%S}||SIU^S12|{evento.cirugia_id}|P|2.5"
        raw += f"\rSCH|{evento.cirugia_id}|{evento.estado_destino.name}"
        self._cliente.enviar_mensaje(raw)


# ------------------------------------------------------ Adapter: pasarelas
class PasarelaPago(Protocol):
    """Interfaz destino del patrón Adapter."""

    def cobrar(self, monto: Decimal, referencia: str) -> bool: ...


class SdkPseExterno:
    def iniciar_transaccion(self, centavos: int, ref: str) -> dict[str, str]:
        return {"estado": "APROBADA", "ref": ref, "centavos": str(centavos)}


class AdaptadorPasarelaPse(PasarelaPago):
    def __init__(self, sdk: SdkPseExterno) -> None:
        self._sdk = sdk

    def cobrar(self, monto: Decimal, referencia: str) -> bool:
        resp = self._sdk.iniciar_transaccion(int(monto * 100), referencia)
        return resp["estado"] == "APROBADA"
