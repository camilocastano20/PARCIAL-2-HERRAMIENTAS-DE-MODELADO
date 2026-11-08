"""Ejemplo de ejecución: un caso correcto y uno de error."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from surgiplan import *

ahora = datetime(2026, 11, 2, 6, 0)
cat = CatalogoTarifas({r: Decimal("100000") for r in RolEquipo}, {t: Decimal("5000") for t in TipoQuirofano})
hosp = Hospital("Hospital Central"); q = Quirofano("Q1", 1, TipoQuirofano.GENERAL); hosp.agregar_quirofano(q)
coord = Coordinador("CO1", "Carla", "c@h.org")
cx = Cirujano("CX1", "Dr. Pérez", "p@h.org"); cx.habilitaciones.append(Habilitacion(Especialidad.CIRUGIA_GENERAL, date(2027, 1, 1)))
an = Anestesiologo("AN1", "Dra. Gómez", "g@h.org"); ci = Enfermero("EC1", "Luis", "l@h.org"); ei = Enfermero("EI1", "Ana", "a@h.org")
proc = Procedimiento("P1", "Colecistectomía", Especialidad.CIRUGIA_GENERAL, 90, NivelContaminacion.LIMPIA_CONTAMINADA, TipoQuirofano.GENERAL)
pac = Paciente("100", "Marta Ruiz", date(1975, 3, 2), "A+", 3, PlanPrepagada())
sol = SolicitudCirugia("S1", cx, pac, proc, TipoCirugia.ELECTIVA, date(2026, 11, 3), "colelitiasis sintomática")
equipo = [(cx, RolEquipo.CIRUJANO_PRINCIPAL), (an, RolEquipo.ANESTESIOLOGO), (ci, RolEquipo.ENFERMERO_CIRCULANTE), (ei, RolEquipo.ENFERMERO_INSTRUMENTISTA)]
canal = CanalCorreo()
srv = ServicioProgramacion()
ini = datetime(2026, 11, 3, 8, 0)

print("== CASO CORRECTO ==")
c = srv.programar_cirugia(coord, sol, q, FranjaHoraria(ini, ini + timedelta(minutes=113)), equipo, [], ahora, cat, [canal])
print(f"Cirugía {c.id}: estado={c.estado.name}, duración mínima (ASA 3)={c.duracion_minima()} min, programada={c.duracion_programada} min")
c.registrar_consentimiento(ConsentimientoInformado("Marta Ruiz", datetime(2026, 10, 30)))
c.registrar_evaluacion_preanestesica(EvaluacionPreanestesica(an, EstadoEvaluacion.APROBADA, ahora), an)
c.confirmar(coord, ahora); print("tras confirmar:", c.estado.name)
c.iniciar(cx, ini); print("tras iniciar:", c.estado.name, "| quirófano:", q.estado.name)
for e in c.eventos: print(f"  auditoría: {e.estado_origen.name if e.estado_origen else '[inicial]'} -> {e.estado_destino.name} por {e.usuario} ({e.evento})")
print("correos enviados:", len(canal.enviados))

print("\n== CASO DE ERROR (cancelar una cirugía EN_CURSO, RN10) ==")
try:
    c.cancelar(coord, ini + timedelta(minutes=5), MotivoCancelacion.DESISTIMIENTO_PACIENTE)
except TransicionInvalidaError as exc:
    print("TransicionInvalidaError:", exc, "| regla =", exc.regla)
print("estado se mantiene:", c.estado.name)

print("\n== CASO DE ERROR (finalizar sin conteo final verificado, RN11) ==")
try:
    c.finalizar_procedimiento(cx, ini + timedelta(minutes=60))
except GuardaIncumplidaError as exc:
    print("GuardaIncumplidaError:", exc, "| regla =", exc.regla)
