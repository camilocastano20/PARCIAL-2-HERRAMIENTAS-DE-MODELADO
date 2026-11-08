"""Pruebas de la bonificación G-16: ResidenteCirugia y ProveedorInsumos."""
import unittest
from datetime import datetime

from surgiplan import *
from surgiplan.extensiones import ProveedorInsumos, ResidenteCirugia, pedir_si_hace_falta
from tests.test_surgiplan import Base, T0, h


class TestExtensiones(Base):
    def setUp(self) -> None:
        super().setUp()
        self.catalogo._honorarios[RolEquipo.OBSERVADOR] = __import__("decimal").Decimal("0")

    def test_residente_observa_pero_no_es_principal_ni_inicia(self) -> None:
        r = ResidenteCirugia("R1", "Residente Uno", "r@h.org")
        c = self.programar(self.q1, h(8), 120)
        c.asignar_profesional(r, RolEquipo.OBSERVADOR)                     # puede observar
        with self.assertRaises(GuardaIncumplidaError):                      # nunca principal
            c.asignar_profesional(ResidenteCirugia("R2", "R2", "r2@h.org"), RolEquipo.CIRUJANO_PRINCIPAL)
        self.preparar_confirmacion(c)
        c.confirmar(self.coord, T0)
        with self.assertRaises(PermisoDenegadoError):                       # nunca inicia
            c.iniciar(r, h(8))                                               # type: ignore[arg-type]
        r.registrar_nota(c.id, "Observación de la técnica", h(9))
        self.assertEqual(len(r.notas), 1)
        self.assertNotIsInstance(r, Cirujano)

    def test_proveedor_depende_de_interfaces(self) -> None:
        p = ProveedorInsumos("Proveedor S.A.", {"G1": 3})
        self.assertIsNone(pedir_si_hace_falta(p, "G1", 2, 10))
        self.assertEqual(pedir_si_hace_falta(p, "G1", 5, 10), "PED-0001")


if __name__ == "__main__":
    unittest.main()
