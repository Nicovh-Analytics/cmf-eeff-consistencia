"""Asignacion de estado financiero (ESF/ERI/ECP/EFE) por orden de codigos XML."""

# Codigos EXCLUSIVOS de cada estado (taxonomia CMF de fondos mutuos, en el
# orden del XML). Los que existen en dos estados (p.ej. diferencias de
# cambio sobre efectivo: ERI y EFE; distribucion de beneficios: ERI y ECP)
# o que no estan en la lista heredan la seccion en curso. Asi la
# clasificacion sigue el orden real del archivo, aunque una AGF ordene los
# estados distinto (p.ej. EFE antes que ECP).
ANCLAS = {
    "ESF": """EfectivoYEfectivoEquivalente ActivosFinancierosAValorRazonableConEfectoEnResultados
        ActivosFinancierosAValorRazonableConEfectoEnResultadosEntregadosEnGarantia
        ActivosFinancierosACostoAmortizado CuentasPorCobrarAIntermediarios OtrasCuentasPorCobrar
        OtrosActivos TotalActivo PasivosFinancierosAValorRazonableConEfectoEnResultados
        CuentasPorAPagarIntermediarios RescatesPorPagar RemuneracionesSociedadAdministradora
        OtrosDocumentosYCuentasPorPagar OtrosPasivos TotalPasivo ActivoNetoAtribuibleALosParticipes""",
    "ERI": """InteresesYReajustes IngresosPorDividendos
        DiferenciasDeCambioNetasSobreActivosFinancierosACostoAmortizado
        CambiosNetosEnValorRazonableDeActivosYPasivosFinancierosAValorRazonableConEfectoEnResultados
        ResultadoEnVentaDeInstrumentosFinancieros OtrosEri TotalIngresosPerdidasNetosDeLaOperacion
        ComisionDeAdministracion HonorariosPorCustodiaYAdministracion CostosDeTransaccion
        OtrosGastosDeOperacion TotalGastosDeOperacion UtilidadPerdidaDeLaOperacionAntesDeImpuesto
        ImpuestosALasGananciasPorInversionesEnElExterior UtilidadPerdidaDeLaOperacionDespuesDeImpuesto
        AumentoDisminucionDeActivoNetoAtribuibleAParticipesOriginadasPorActividadesDeLaOperacionAntesDeDistribucionDeBeneficios
        AumentoDisminucionDeActivoNetoAtribuibleAParticipesOriginadasPorActividadesDeLaOperacionDespuesDeDistribucionDeBeneficios""",
    "ECP": """ActivoNetoAtribuibleALosParticipesAl01DeEneroPorSerie ActivoNetoAtribuibleALosParticipesAl01DeEnero
        AportesDeCuotasPorSerie AportesDeCuotas RescateDeCuotasPorSerie RescateDeCuotas
        AumentoNetoOriginadoPorTransaccionesDeCuotasPorSerie AumentoNetoOriginadoPorTransaccionesDeCuotas
        AumentoDisminucionDelActivoNetoAtribuibleAParticipesOriginadasPorActividadesDeLaOperacionAntesDeDistribucionDeBeneficiosPorSerie
        AumentoDisminucionDelActivoNetoAtribuibleAParticipesOriginadasPorActividadesDeLaOperacionAntesDeDistribucionDeBeneficios
        DistribucionDeBeneficiosPorSerie DistribucionDeBeneficiosEnEfectivoPorSerie DistribucionDeBeneficiosEnEfectivo
        DistribucionDeBeneficiosEnCuotasPorSerie DistribucionDeBeneficiosEnCuotas
        AumentoDisminucionDelActivoNetoAtribuibleAParticipesOriginadasPorActividadesDeLaOperacionDespuesDeDistribucionDeBeneficiosPorSerie
        AumentoDisminucionDelActivoNetoAtribuibleAParticipesOriginadasPorActividadesDeLaOperacionDespuesDeDistribucionDeBeneficios
        ActivoNetoAtribuibleAParticipesAl31DeDiciembreValorCuotaPorSerie ActivoNetoAtribuibleAParticipesAl31DeDiciembreValorCuota""",
    "EFE": """CompraDeActivosFinancieros VentaCobroDeActivosFinancieros InteresesDiferenciasDeCambioYReajustesRecibidos
        LiquidacionDeInstrumentosFinancierosDerivados DividendosRecibidos
        MontosPagadosASociedadAdministradoraEIntermediarios MontosRecibidosDeSociedadAdministradoraEIntermediarios
        OtrosIngresosDeOperacion OtrosGastosDeOperacionPagados FlujoNetoOriginadoPorActividadesDeLaOperacion
        ColocacionDeCuotasEnCirculacion RescatesDeCuotasEnCirculacion Otros
        FlujoNetoOriginadoPorActividadesDeFinanciamiento AumentoNetoDeEfectivoYEfectivoEquivalente
        SaldoInicialDeEfectivoYEfectivoEquivalente SaldoFinalDeEfectivoYEfectivoEquivalente
        AumentoDisminucionDelActivoNetoAtribuibleAParticipesOriginadasPorActividadesDeLaOperacionDespuesDeLaDistribucionDeBeneficios
        AjustesPorInteresesDiferenciasDeCambioYReajustesDevengadosNoRealizados AjustesPorIngresosPorDividendosNoRealizados
        AjustesPorDiferenciasDeCambioNoRealizadasSobreEfectivoYEfectivoEquivalente
        AjustesPorOtrasVariacionesDeResultadosNoRealizadas SubtotalAjustes
        AumentoNetoDeActivosFinancierosAValorRazonableConEfectoEnResultados
        AumentoNetoDePasivosFinancierosAValorRazonableConEfectoEnResultados AumentoNetoDeOtrosDeudoresYAcreedores
        AumentoDisminucionNetaDeCuentasPorPagarCobrarAIntermediarios
        AumentoDisminucionNetaDeCuentasPorPagarCobrarALaSociedadAdministradora
        SubtotalEfectivoUtilizadoEnOperaciones FlujoNetoUtilizadoEnActividadesDeLaOperacion
        RescateDeCuotasEnCirculacion DistribucionesPagadasAParticipes FlujoNetoUtilizadoPorActividadesDeFinanciamiento
        AumentoDisminucionNetoDeEfectivoYEfectivoEquivalente""",
}
SECCION_DE = {c: est for est, txt in ANCLAS.items() for c in txt.split()}


def asignar_secciones(codigos):
    """Recorre los codigos en el orden del XML; un codigo exclusivo fija la
    seccion, los demas heredan la vigente."""
    actual, out = "ESF", []
    for c in codigos:
        actual = SECCION_DE.get(c, actual)
        out.append(actual)
    return out