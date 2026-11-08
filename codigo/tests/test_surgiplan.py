"""Pruebas unitarias de SurgiPlan (Parte E-14). Ejecutar: python -m unittest -v"""
from __future__ import annotations

import dataclasses
import unittest
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from surgiplan import *  # noqa: F401,F403
from surgiplan.cirugia import Cirugia


T0 = datetime(2026, 11, 2, 6, 0)            # "ahora" de programación
DIA = datetime(2026, 11, 3, 0, 0)           # día de las cirugías


def h(hora: int, minuto: int = 0, dia: datetime = DIA) -> datetime:
    return dia.replace(hour=hora, minute=minuto)


@dataclass
class Equipo4:
    cirujano: Cirujano
    anest: Anestesiologo
    circ: Enfermero
    instr: Enfermero

    def lista(self) -> list[tuple[PersonalClinico, RolEquipo]]:
        return [
            (self.cirujano, RolEquipo.CIRUJANO_PRINCIPAL),
            (self.anest, RolEquipo.ANESTESIOLOGO),
            (self.circ, RolEquipo.ENFERMERO_CIRCULANTE),
            (self.instr, RolEquipo.ENFERMERO_INSTRUMENTISTA),
        ]


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.n = 0
        self.catalogo = CatalogoTarifas(
            {
                RolEquipo.CIRUJANO_PRINCIPAL: Decimal("1000000"),
                RolEquipo.CIRUJANO_ASISTENTE: Decimal("500000"),
                RolEquipo.ANESTESIOLOGO: Decimal("800000"),
                RolEquipo.ENFERMERO_CIRCULANTE: Decimal("300000"),
                RolEquipo.ENFERMERO_INSTRUMENTISTA: Decimal("300000"),
            },
            {t: Decimal("5000") for t in TipoQuirofano},
        )
        self.hospital = Hospital("Hospital Central")
        self.q1, self.q2, self.q3 = (Quirofano(f"Q{i}", 1, TipoQuirofano.GENERAL) for i in (1, 2, 3))
        self.q_orto = Quirofano("QO", 2, TipoQuirofano.ORTOPEDICO)
        for q in (self.q1, self.q2, self.q3, self.q_orto):
            self.hospital.agregar_quirofano(q)
        self.coord = Coordinador("CO1", "Carla Coordinadora", "c@h.org")
        self.servicio = ServicioProgramacion()
        self.canal = CanalCorreo()
        self.p_limpia = Procedimiento("P1", "Apendicectomía", Especialidad.CIRUGIA_GENERAL, 90,
                                      NivelContaminacion.LIMPIA, TipoQuirofano.GENERAL, (TipoEquipo.TORRE_LAPAROSCOPICA,))
        self.p_sucia = Procedimiento("P2", "Drenaje de absceso", Especialidad.CIRUGIA_GENERAL, 60,
                                     NivelContaminacion.SUCIA, TipoQuirofano.GENERAL)
        self.p_emerg = Procedimiento("P3", "Laparotomía exploratoria", Especialidad.CIRUGIA_GENERAL, 60,
                                     NivelContaminacion.CONTAMINADA, TipoQuirofano.GENERAL)
        self.p_orto = Procedimiento("P4", "Prótesis de cadera", Especialidad.ORTOPEDIA, 120,
                                    NivelContaminacion.LIMPIA, TipoQuirofano.ORTOPEDICO)

    # ---- fábricas
    def equipo(self, completo: bool = True) -> Equipo4:
        self.n += 1
        n = self.n
        cx = Cirujano(f"CX{n}", f"Cirujano {n}", "x@h.org")
        cx.habilitaciones = [Habilitacion(e, date(2027, 12, 31)) for e in Especialidad]
        return Equipo4(cx, Anestesiologo(f"AN{n}", f"Anest {n}", "a@h.org"),
                       Enfermero(f"EC{n}", f"Circulante {n}", "c@h.org"), Enfermero(f"EI{n}", f"Instrum {n}", "i@h.org"))

    def torre(self) -> EquipoMedico:
        self.n += 1
        t = EquipoMedico(f"T{self.n}", TipoEquipo.TORRE_LAPAROSCOPICA)
        self.hospital.agregar_equipo(t)
        return t

    def solicitud(self, proc: Procedimiento, tipo: TipoCirugia = TipoCirugia.ELECTIVA, asa: int = 2, equipo: Equipo4 | None = None,
                  nacimiento: date = date(1980, 5, 5)) -> SolicitudCirugia:
        self.n += 1
        eq = equipo or self.equipo()
        pac = Paciente(f"D{self.n}", f"Paciente {self.n}", nacimiento, "O+", asa, PlanEps())
        return SolicitudCirugia(f"S{self.n}", eq.cirujano, pac, proc, tipo, DIA.date(), "justificación clínica")

    def programar(self, q: Quirofano, ini: datetime, minutos: int, proc: Procedimiento | None = None,
                  tipo: TipoCirugia = TipoCirugia.ELECTIVA, asa: int = 2, eq: Equipo4 | None = None, ahora: datetime = T0) -> Cirugia:
        proc = proc or self.p_limpia
        eq = eq or self.equipo()
        sol = self.solicitud(proc, tipo, asa, eq)
        equipos = [self.torre() for _ in proc.tipos_equipo_requeridos]
        return self.servicio.programar_cirugia(self.coord, sol, q, FranjaHoraria(ini, ini + timedelta(minutes=minutos)),
                                               eq.lista(), equipos, ahora, self.catalogo, [self.canal])

    def preparar_confirmacion(self, c: Cirugia, firmado: datetime = h(0) - timedelta(days=10)) -> None:
        c.registrar_consentimiento(ConsentimientoInformado("paciente", firmado))
        anest = c.anestesiologo()
        assert anest is not None
        c.registrar_evaluacion_preanestesica(EvaluacionPreanestesica(anest, EstadoEvaluacion.APROBADA, T0), anest)

    def en_curso(self, c: Cirugia) -> Cirujano:
        self.preparar_confirmacion(c)
        c.confirmar(self.coord, T0)
        cx = c.cirujano_principal()
        assert cx is not None
        c.iniciar(cx, c.franja.inicio)
        return cx


class TestFranja(unittest.TestCase):
    def test_semiabierto(self) -> None:
        a = FranjaHoraria(h(8), h(10))
        self.assertFalse(a.solapa_con(FranjaHoraria(h(10), h(12))))
        self.assertTrue(a.solapa_con(FranjaHoraria(h(9, 59), h(12))))

    def test_validacion_y_valor(self) -> None:
        with self.assertRaises(FranjaInvalidaError):
            FranjaHoraria(h(10), h(10))
        self.assertEqual(FranjaHoraria(h(8), h(9)), FranjaHoraria(h(8), h(9)))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            FranjaHoraria(h(8), h(9)).inicio = h(7)  # type: ignore[misc]


class TestProgramacion(Base):
    def test_01_franjas_contiguas_respetan_limpieza(self) -> None:
        a = self.programar(self.q1, h(8), 90)                       # LIMPIA -> 20 min
        b = self.programar(self.q1, h(9, 50), 90)                   # exactamente 20 min después
        self.assertEqual((a.estado, b.estado), (EstadoCirugia.PROGRAMADA, EstadoCirugia.PROGRAMADA))
        with self.assertRaises(ConflictoProgramacionError) as ctx:  # 19 min: insuficiente
            self.programar(self.q2, h(8), 90) and self.programar(self.q2, h(9, 49), 90)
        self.assertEqual(ctx.exception.regla, "RN1")

    def test_02_solapamiento_rechazado_rn1(self) -> None:
        self.programar(self.q1, h(8), 120)
        with self.assertRaises(ConflictoProgramacionError) as ctx:
            self.programar(self.q1, h(9), 120)
        self.assertEqual(ctx.exception.regla, "RN1")

    def test_03_sin_circulante_rechazado_rn2(self) -> None:
        eq = self.equipo()
        sol = self.solicitud(self.p_sucia, equipo=eq)
        parcial = [x for x in eq.lista() if x[1] is not RolEquipo.ENFERMERO_CIRCULANTE]
        with self.assertRaises(GuardaIncumplidaError) as ctx:
            self.servicio.programar_cirugia(self.coord, sol, self.q1, FranjaHoraria(h(8), h(10)), parcial, [], T0, self.catalogo)
        self.assertEqual(ctx.exception.regla, "RN2")
        self.assertIn("circulante", str(ctx.exception))

    def test_rn2_un_profesional_un_rol(self) -> None:
        eq = self.equipo()
        c = Cirugia("X", self.solicitud(self.p_sucia, equipo=eq), self.q1, FranjaHoraria(h(8), h(10)), self.coord, self.catalogo)
        c.asignar_profesional(eq.cirujano, RolEquipo.CIRUJANO_PRINCIPAL)
        with self.assertRaises(GuardaIncumplidaError):
            c.asignar_profesional(eq.cirujano, RolEquipo.CIRUJANO_ASISTENTE)

    def test_rn3_tope_12_horas(self) -> None:
        eq = self.equipo()
        self.programar(self.q_orto, h(6), 480, proc=self.p_orto, eq=eq)          # 8 h
        with self.assertRaises(ConflictoProgramacionError) as ctx:
            self.programar(self.q2, h(14, 30), 270, proc=self.p_sucia, eq=eq)    # +4,5 h = 12,5 h
        self.assertEqual(ctx.exception.regla, "RN3")

    def test_rn3_solape_de_profesional(self) -> None:
        eq = self.equipo()
        self.programar(self.q1, h(8), 120, eq=eq)
        with self.assertRaises(ConflictoProgramacionError) as ctx:
            self.programar(self.q2, h(9), 120, proc=self.p_sucia, eq=eq)
        self.assertEqual(ctx.exception.regla, "RN3")

    def test_rn4_habilitacion_vencida(self) -> None:
        eq = self.equipo()
        eq.cirujano.habilitaciones = [Habilitacion(Especialidad.CIRUGIA_GENERAL, date(2026, 11, 2))]
        with self.assertRaises(GuardaIncumplidaError) as ctx:
            self.programar(self.q1, h(8), 120, eq=eq)
        self.assertEqual(ctx.exception.regla, "RN4")

    def test_rn5_recargo_asa(self) -> None:
        with self.assertRaises(GuardaIncumplidaError) as ctx:
            self.programar(self.q1, h(8), 100, asa=3)           # mínimo 113 min
        self.assertEqual(ctx.exception.regla, "RN5")
        c = self.programar(self.q1, h(8), 113, asa=3)
        self.assertEqual(c.duracion_minima(), 113)
        self.assertEqual(self.programar(self.q2, h(8), 90, asa=2).duracion_minima(), 90)

    def test_rn5_inicio_pasado_solo_emergencia(self) -> None:
        with self.assertRaises(GuardaIncumplidaError):
            self.programar(self.q1, h(8), 120, ahora=h(9))

    def test_rn6_equipo_no_operativo(self) -> None:
        eq = self.equipo()
        c = Cirugia("X", self.solicitud(self.p_limpia, equipo=eq), self.q1, FranjaHoraria(h(8), h(10)), self.coord, self.catalogo)
        t = self.torre()
        t.estado = EstadoEquipo.EN_MANTENIMIENTO
        with self.assertRaises(GuardaIncumplidaError) as ctx:
            c.reservar_equipo(t)
        self.assertEqual(ctx.exception.regla, "RN6")

    def test_rn7_una_cirugia_por_solicitud(self) -> None:
        eq = self.equipo()
        sol = self.solicitud(self.p_sucia, equipo=eq)
        self.servicio.programar_cirugia(self.coord, sol, self.q1, FranjaHoraria(h(8), h(10)), eq.lista(), [], T0, self.catalogo)
        with self.assertRaises(GuardaIncumplidaError) as ctx:
            self.servicio.programar_cirugia(self.coord, sol, self.q2, FranjaHoraria(h(8), h(10)), eq.lista(), [], T0, self.catalogo)
        self.assertEqual(ctx.exception.regla, "RN7")


class TestConfirmacionYPermisos(Base):
    def test_rn8_consentimiento_antiguo(self) -> None:
        c = self.programar(self.q1, h(8), 120)
        self.preparar_confirmacion(c, firmado=h(0) - timedelta(days=31))
        with self.assertRaises(GuardaIncumplidaError) as ctx:
            c.confirmar(self.coord, T0)
        self.assertEqual(ctx.exception.regla, "RN8")
        self.preparar_confirmacion(c, firmado=h(0) - timedelta(days=30))
        c.confirmar(self.coord, T0)
        self.assertEqual(c.estado, EstadoCirugia.CONFIRMADA)

    def test_rn8_menor_exige_representante(self) -> None:
        eq = self.equipo()
        sol = self.solicitud(self.p_sucia, equipo=eq, nacimiento=date(2015, 1, 1))
        c = self.servicio.programar_cirugia(self.coord, sol, self.q1, FranjaHoraria(h(8), h(10)), eq.lista(), [], T0, self.catalogo)
        self.preparar_confirmacion(c)
        with self.assertRaises(GuardaIncumplidaError):
            c.confirmar(self.coord, T0)
        c.registrar_consentimiento(ConsentimientoInformado("madre", h(0) - timedelta(days=2), True, True))
        c.confirmar(self.coord, T0)

    def test_rn8_sin_evaluacion_aprobada(self) -> None:
        c = self.programar(self.q1, h(8), 120)
        c.registrar_consentimiento(ConsentimientoInformado("paciente", h(0) - timedelta(days=1)))
        with self.assertRaises(GuardaIncumplidaError):
            c.confirmar(self.coord, T0)

    def test_rn16_permisos(self) -> None:
        c = self.programar(self.q1, h(8), 120)
        self.preparar_confirmacion(c)
        with self.assertRaises(PermisoDenegadoError):
            c.confirmar(Auditor("AU", "Aud", "a@h"), T0)
        c.confirmar(self.coord, T0)
        otro = self.equipo().cirujano
        with self.assertRaises(PermisoDenegadoError):
            c.iniciar(otro, h(8))

    def test_rn10_vencimiento_45_min(self) -> None:
        c = self.programar(self.q1, h(8), 120)
        self.preparar_confirmacion(c)
        c.confirmar(self.coord, T0)
        self.assertFalse(c.verificar_vencimiento(h(8, 45)))
        self.assertTrue(c.verificar_vencimiento(h(8, 46)))
        self.assertEqual(c.estado, EstadoCirugia.POSPUESTA)
        self.assertEqual(c.eventos[-1].usuario, "SISTEMA")
        self.assertFalse(c.reservas_activas())

    def test_rn13_cancelacion_tardia(self) -> None:
        c = self.programar(self.q1, h(8), 120)
        c.cancelar(self.coord, h(0) + timedelta(hours=-10), MotivoCancelacion.DESISTIMIENTO_PACIENTE)
        self.assertTrue(c.cancelacion_tardia)            # 8:00 - (23:xx anterior) < 24 h
        c2 = self.programar(self.q2, h(8), 120)
        c2.cancelar(self.coord, T0 - timedelta(days=2), MotivoCancelacion.PACIENTE_NO_APTO)
        self.assertFalse(c2.cancelacion_tardia)
        self.assertEqual(c2.estado, EstadoCirugia.CANCELADA)


class TestMaquinaEstados(Base):
    def test_04_cancelar_en_curso_rechazado(self) -> None:
        c = self.programar(self.q1, h(8), 120)
        self.en_curso(c)
        with self.assertRaises(TransicionInvalidaError) as ctx:
            c.cancelar(self.coord, h(8, 10), MotivoCancelacion.OTRO_CATALOGADO)
        self.assertEqual(ctx.exception.regla, "RN10")
        self.assertIn("EN_CURSO", str(ctx.exception))
        c.interrumpir(c.cirujano_principal(), h(8, 20))  # type: ignore[arg-type]
        with self.assertRaises(TransicionInvalidaError):
            c.cancelar(self.coord, h(8, 25), MotivoCancelacion.OTRO_CATALOGADO)

    def test_05_cancelada_no_reprogramable(self) -> None:
        c = self.programar(self.q1, h(8), 120)
        c.cancelar(self.coord, T0, MotivoCancelacion.ERROR_DE_PROGRAMACION)
        with self.assertRaises(TransicionInvalidaError):
            c.reprogramar(self.coord, T0)
        with self.assertRaises(TransicionInvalidaError):
            c.posponer(self.coord, T0)

    def test_06_cierre_sin_conteo_final_verificado_rechazado(self) -> None:
        c = self.programar(self.q1, h(8), 120)
        cx = self.en_curso(c)
        circ = c.enfermero_circulante()
        with self.assertRaises(GuardaIncumplidaError) as ctx:       # CIERRE sin conteo inicial
            c.pasar_a_procedimiento(cx, h(8, 5))
            c.entrar_cierre(cx, h(8, 30))
        self.assertEqual(ctx.exception.regla, "RN11")
        c.registrar_conteo_inicial(circ, h(8, 10), 40)  # type: ignore[arg-type]
        c.entrar_cierre(cx, h(9))
        with self.assertRaises(GuardaIncumplidaError) as ctx2:      # finalizar sin conteo final verificado
            c.finalizar_procedimiento(cx, h(9, 30))
        self.assertEqual(ctx2.exception.regla, "RN11")
        c.registrar_conteo_final(circ, h(9, 20), 39)  # type: ignore[arg-type]
        with self.assertRaises(GuardaIncumplidaError):              # diferencia 1 sin incidente resuelto
            c.verificar_conteo_final(circ, h(9, 21))  # type: ignore[arg-type]
        inc = c.registrar_incidente_instrumental("pinza no contada")
        c.resolver_control_radiologico(inc)
        c.verificar_conteo_final(circ, h(9, 25))  # type: ignore[arg-type]
        c.finalizar_procedimiento(cx, h(9, 30))
        self.assertEqual(c.estado, EstadoCirugia.EN_RECUPERACION)

    def test_flujo_completo_costos_y_quirofano(self) -> None:
        c = self.programar(self.q1, h(8), 120)
        cx = self.en_curso(c)
        circ = c.enfermero_circulante()
        self.assertEqual(self.q1.estado, EstadoQuirofano.OCUPADO)
        c.registrar_consumo(Insumo("G1", "Gasas", Decimal("10000")), 2, h(8, 5))
        c.registrar_conteo_inicial(circ, h(8, 6), 40)  # type: ignore[arg-type]
        c.pasar_a_procedimiento(cx, h(8, 10))
        c.entrar_cierre(cx, h(9, 10))
        c.registrar_conteo_final(circ, h(9, 15), 40)  # type: ignore[arg-type]
        c.verificar_conteo_final(circ, h(9, 16))  # type: ignore[arg-type]
        c.finalizar_procedimiento(cx, h(9, 20))      # 80 min reales
        self.assertEqual(self.q1.estado, EstadoQuirofano.EN_LIMPIEZA)
        self.assertFalse(c.reservas_activas())
        self.q1.registrar_limpieza_realizada()
        self.assertEqual(self.q1.estado, EstadoQuirofano.DISPONIBLE)
        with self.assertRaises(GuardaIncumplidaError) as ctx:
            c.dar_alta(cx, h(10))
        self.assertEqual(ctx.exception.regla, "ALTA")
        c.registrar_informe_operatorio(InformeOperatorio(True, cx))
        c.registrar_aldrete(9)
        c.dar_alta(cx, h(10))
        self.assertEqual(c.estado, EstadoCirugia.COMPLETADA)
        # RN14: 2.400.000 honorarios + 80*5000 + 2*10000
        self.assertEqual(c.costo_total, Decimal("2820000"))
        self.catalogo.actualizar_tarifa_minuto(TipoQuirofano.GENERAL, Decimal("9000"))   # no altera lo histórico
        self.assertEqual(c.costo_total, Decimal("2820000"))
        self.assertEqual(c.valor_a_cargo_paciente(), Decimal("282000.00"))   # EPS 10 %
        # RN15: una auditoría por transición (5 de estado + 4 internas)
        self.assertEqual(len([e for e in c.eventos if e.estado_origen != e.estado_destino]), 5)
        self.assertEqual(len(c.eventos), 9)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            c.eventos[0].motivo = "x"  # type: ignore[misc]

    def test_historia_profunda_al_reanudar(self) -> None:
        c = self.programar(self.q1, h(8), 120)
        cx = self.en_curso(c)
        circ = c.enfermero_circulante()
        c.registrar_conteo_inicial(circ, h(8, 5), 30)  # type: ignore[arg-type]
        c.pasar_a_procedimiento(cx, h(8, 10))
        c.interrumpir(cx, h(8, 30), "falla eléctrica")
        self.assertEqual(self.q1.estado, EstadoQuirofano.OCUPADO)           # RN12
        c.reanudar(cx, h(8, 40))
        self.assertEqual((c.fase_clinica, c.control_instrumental),
                         (FaseClinica.PROCEDIMIENTO, EstadoConteo.CONTEO_INICIAL_REGISTRADO))
        self.assertEqual(c.minutos_reales, 30)

    def test_aborto_clinico_desde_interrumpida(self) -> None:
        c = self.programar(self.q1, h(8), 120)
        cx = self.en_curso(c)
        c.interrumpir(cx, h(8, 30))
        with self.assertRaises(GuardaIncumplidaError):
            c.abortar(cx, h(8, 35), "")
        c.abortar(cx, h(8, 35), "inestabilidad hemodinámica")
        self.assertEqual((c.estado, self.q1.estado), (EstadoCirugia.EN_RECUPERACION, EstadoQuirofano.EN_LIMPIEZA))
        self.assertTrue(c.abortada)

    def test_posponer_y_reprogramar_no_crean_cirugia_nueva(self) -> None:
        c = self.programar(self.q1, h(8), 120)
        c.posponer(self.coord, T0, "paciente con fiebre")
        self.assertEqual(self.q1.estado, EstadoQuirofano.DISPONIBLE)        # RN12: sin cambio
        self.assertFalse(c.reservas_activas())
        with self.assertRaises(GuardaIncumplidaError):                       # falta re-reservar la torre (RN6)
            c.reprogramar(self.coord, T0, self.q2, FranjaHoraria(h(10), h(12)))
        c.reservar_equipo(self.torre())
        c.reprogramar(self.coord, T0, self.q2, FranjaHoraria(h(10), h(12)))
        self.assertEqual((c.estado, c.quirofano), (EstadoCirugia.PROGRAMADA, self.q2))
        self.assertIs(c.solicitud.cirugia, c)

    def test_quirofano_maquina_propia(self) -> None:
        self.q3.iniciar_mantenimiento()
        self.assertEqual(self.q3.estado, EstadoQuirofano.EN_MANTENIMIENTO)
        with self.assertRaises(TransicionInvalidaError):
            self.q3.registrar_limpieza_realizada()
        self.q3.finalizar_mantenimiento()
        self.assertEqual(self.q3.estado, EstadoQuirofano.DISPONIBLE)

    def test_notificacion_por_canales_y_fallo_aislado(self) -> None:
        class CanalRoto(CanalNotificacion):
            def notificar(self, evento, destinatarios):  # type: ignore[no-untyped-def]
                raise RuntimeError("caído")

        c = self.programar(self.q1, h(8), 120)
        c.canales.append(CanalRoto())
        c.posponer(self.coord, T0)
        self.assertEqual(c.estado, EstadoCirugia.POSPUESTA)       # la transición no se revierte
        self.assertEqual(len(c.fallos_notificacion), 1)
        self.assertGreaterEqual(len(self.canal.enviados), 6)        # 2 eventos x 3 destinatarios


class TestEmergencia(Base):
    def _ocupar_tres(self, tipo3: TipoCirugia = TipoCirugia.URGENTE) -> tuple[Cirugia, Cirugia, Cirugia]:
        c1 = self.programar(self.q1, h(8), 120, asa=3)
        c2 = self.programar(self.q2, h(8), 120, asa=2)
        c3 = self.programar(self.q3, h(8), 120, tipo=tipo3, asa=1)
        return c1, c2, c3

    def _emergencia(self, eq: Equipo4 | None = None, ini: datetime = h(8, 30)):  # type: ignore[no-untyped-def]
        eq = eq or self.equipo()
        sol = self.solicitud(self.p_emerg, TipoCirugia.EMERGENCIA, 4, eq)
        just = JustificacionEmergencia("riesgo vital inminente", eq.cirujano, T0)
        return sol, eq, just, FranjaHoraria(ini, ini + timedelta(minutes=75))

    def test_07_emergencia_desplaza_a_la_electiva_correcta(self) -> None:
        c1, c2, c3 = self._ocupar_tres()
        sol, eq, just, franja = self._emergencia()
        reservas_c2 = c2.reservas_activas()
        self.assertTrue(reservas_c2)
        e = self.servicio.programar_emergencia(self.coord, sol, self.hospital, franja, eq.lista(), [], just, T0, self.catalogo, [self.canal])
        # menor ASA entre electivas (c2, ASA 2); la URGENTE (ASA 1) nunca se desplaza
        self.assertEqual(c2.estado, EstadoCirugia.POSPUESTA)
        self.assertEqual((c1.estado, c3.estado), (EstadoCirugia.PROGRAMADA, EstadoCirugia.PROGRAMADA))
        self.assertTrue(all(not r.activa for r in reservas_c2))      # RN12: reservas liberadas
        self.assertIn("Desplazada por emergencia", c2.eventos[-1].motivo or "")
        self.assertIs(e.quirofano, self.q2)
        self.assertEqual(e.estado, EstadoCirugia.CONFIRMADA)         # RN8 sustitutivo
        self.assertIsNotNone(e.limite_consentimiento)

    def test_rn9_desempate_inicio_mas_tardio(self) -> None:
        a = self.programar(self.q1, h(8), 120, asa=2)
        b = self.programar(self.q2, h(8, 10), 120, asa=2)           # mismo ASA, inicio más tardío
        sol, eq, just, franja = self._emergencia(ini=h(9))
        self.programar(self.q3, h(8), 240, tipo=TipoCirugia.URGENTE)
        self.servicio.programar_emergencia(self.coord, sol, self.hospital, franja, eq.lista(), [], just, T0, self.catalogo)
        self.assertEqual((a.estado, b.estado), (EstadoCirugia.PROGRAMADA, EstadoCirugia.POSPUESTA))

    def test_rn9_ninguna_electiva_desplazable(self) -> None:
        c1, c2, c3 = (self.programar(q, h(8), 120, tipo=TipoCirugia.URGENTE) for q in (self.q1, self.q2, self.q3))
        sol, eq, just, franja = self._emergencia()
        with self.assertRaises(SinQuirofanoDisponibleError):
            self.servicio.programar_emergencia(self.coord, sol, self.hospital, franja, eq.lista(), [], just, T0, self.catalogo)
        self.assertTrue(all(c.estado is EstadoCirugia.PROGRAMADA for c in (c1, c2, c3)))

    def test_rn9_no_desplaza_en_curso(self) -> None:
        c1, c2, c3 = self._ocupar_tres(TipoCirugia.ELECTIVA)
        self.en_curso(c1)
        with self.assertRaises(TransicionInvalidaError) as ctx:
            c1.desplazar_por_emergencia(self.coord, c2, T0)
        self.assertEqual(ctx.exception.regla, "RN9")

    def test_rn3_en_emergencia_no_desplaza_si_falla(self) -> None:
        c1, c2, c3 = self._ocupar_tres()
        eq = self.equipo()
        self.programar(self.q_orto, h(12), 690, proc=self.p_orto, eq=eq)    # 11,5 h ese día
        sol, _, just, franja = self._emergencia(eq)
        with self.assertRaises(ConflictoProgramacionError) as ctx:
            self.servicio.programar_emergencia(self.coord, sol, self.hospital, franja, eq.lista(), [], just, T0, self.catalogo)
        self.assertEqual(ctx.exception.regla, "RN3")
        self.assertEqual(c2.estado, EstadoCirugia.PROGRAMADA)                # nada se desplazó (atomicidad)

    def test_idempotencia_de_la_solicitud_de_desplazamiento(self) -> None:
        self._ocupar_tres()
        sol, eq, just, franja = self._emergencia()
        args = (self.coord, sol, self.hospital, franja, eq.lista(), [], just, T0, self.catalogo)
        e1 = self.servicio.programar_emergencia(*args, clave_idempotencia="req-1")
        n = len(self.q2.cirugias)
        e2 = self.servicio.programar_emergencia(*args, clave_idempotencia="req-1")   # reintento de red
        self.assertIs(e1, e2)
        self.assertEqual(len(self.q2.cirugias), n)

    def test_bloqueo_optimista_dos_coordinadores(self) -> None:
        v = self.q1.version                                           # ambos leyeron la misma versión
        self.programar(self.q1, h(8), 120)                            # el primero gana
        eq = self.equipo()
        sol = self.solicitud(self.p_sucia, equipo=eq)
        with self.assertRaises(ConflictoVersionError):
            self.servicio.programar_cirugia(self.coord, sol, self.q1, FranjaHoraria(h(14), h(16)), eq.lista(), [], T0, self.catalogo, version_quirofano=v)


if __name__ == "__main__":
    unittest.main(verbosity=2)
