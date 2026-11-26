# modulos/modulo4.py
import io
import uuid
import calendar
import urllib.parse
from datetime import datetime, date, timedelta
import pandas as pd
import streamlit as st
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from storage import guardar_datos

ETAPAS_EVENTO = [
    "📝 Borrador (Para Junta)",
    "🤝 En Junta / Revisión",
    "✅ Aprobado en Ejecución",
    "🏆 Completado / Realizado",
    "❌ Cancelado"
]

OPCIONES_DECISION = [
    "⏳ Pendiente",
    "✅ Aprobado",
    "❌ No aprobado"
]

MESES_ES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
]


def _obtener_decision_item(item):
    """Compatibilidad con ítems creados anteriormente o con el nuevo selector."""
    if "decision" in item and item["decision"] in OPCIONES_DECISION:
        return item["decision"]
    return "✅ Aprobado" if item.get("aprobado") else "⏳ Pendiente"


def _calcular_avance_evento(ev):
    """Calcula el porcentaje de avance considerando ítems aprobados y pagados."""
    etapa = ev.get("etapa", ETAPAS_EVENTO[0])
    if etapa == "🏆 Completado / Realizado":
        return 100.0
    if etapa == "❌ Cancelado":
        return 0.0

    checklist = ev.get("checklist", [])
    activos = [i for i in checklist if _obtener_decision_item(i) != "❌ No aprobado"]

    if not activos:
        mapa_etapas = {
            "📝 Borrador (Para Junta)": 15.0,
            "🤝 En Junta / Revisión": 40.0,
            "✅ Aprobado en Ejecución": 75.0
        }
        return mapa_etapas.get(etapa, 10.0)

    puntos = 0.0
    for item in activos:
        dec = _obtener_decision_item(item)
        if dec == "✅ Aprobado":
            puntos += 0.5
        if item.get("pagado"):
            puntos += 0.5

    return round((puntos / len(activos)) * 100, 1)


def _formatear_rango_fechas(f_ini_str, f_fin_str):
    """Formatea si el evento es de 1 día o un rango de varios días."""
    try:
        d1 = datetime.strptime(f_ini_str, "%Y-%m-%d").date()
        d2 = datetime.strptime(f_fin_str, "%Y-%m-%d").date()
        dias = (d2 - d1).days + 1
        if d1 == d2:
            return f"{d1.strftime('%d/%m/%Y')} (1 día)"
        return f"{d1.strftime('%d/%m/%Y')} al {d2.strftime('%d/%m/%Y')} ({dias} días)"
    except Exception:
        return f"{f_ini_str} - {f_fin_str}"


def _calcular_totales_presupuesto(checklist):
    """Calcula la suma total cotizada, lo aprobado/autorizado en junta y lo ya pagado."""
    total_cotizado = sum(float(i.get("costo", 0)) for i in checklist)
    total_aprobado = sum(
        float(i.get("costo", 0)) for i in checklist
        if _obtener_decision_item(i) == "✅ Aprobado"
    )
    total_pagado = sum(
        float(i.get("costo", 0)) for i in checklist
        if i.get("pagado") and _obtener_decision_item(i) != "❌ No aprobado"
    )
    return total_cotizado, total_aprobado, total_pagado


# =============================================================================
# GENERACIÓN E IMPORTACIÓN DE PLANTILLA EXCEL (.XLSX)
# =============================================================================
def _generar_plantilla_excel_bytes(marca_activa, todas_las_marcas):
    """Genera en memoria la plantilla Excel lista para compartir y llenar."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Requerimiento Evento"

    fill_navy = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    fill_slate = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
    fill_input = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    fill_note = PatternFill(start_color="EFF6FF", end_color="EFF6FF", fill_type="solid")

    font_sec = Font(color="FFFFFF", bold=True, size=11)
    font_lbl = Font(color="0F172A", bold=True, size=10)
    font_val = Font(color="1E293B", size=10)
    font_hint = Font(color="475569", italic=True, size=9)

    borde = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1")
    )

    # Banner instructivo superior
    ws.merge_cells("A1:D1")
    ws["A1"] = f"PLANTILLA DE REQUERIMIENTO DE EVENTO  |  Marcas disponibles: {', '.join(todas_las_marcas)}"
    ws["A1"].fill = fill_note
    ws["A1"].font = Font(color="1E3A8A", bold=True, size=10)
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 24

    # SECCIÓN 1: DATOS GENERALES
    ws.merge_cells("A3:D3")
    ws["A3"] = "1. DATOS GENERALES DEL EVENTO"
    ws["A3"].fill = fill_navy
    ws["A3"].font = font_sec
    ws.row_dimensions[3].height = 24

    fecha_sugerida = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")
    campos_sec1 = [
        ("Nombre del Evento *:", "", "Ej. Rodada Nocturna / Open House Fin de Mes"),
        ("Marcas Asociadas (separadas por coma) *:", marca_activa, "Si participan varias marcas, sepáralas con coma"),
        ("¿Quién lo solicita?:", "", "Ej. Gerencia de Ventas / Sucursal Ecatepec"),
        ("Responsable de Marketing:", "Área de Marketing", "Nombre del responsable asignado"),
        ("Fecha de Inicio (AAAA-MM-DD) *:", fecha_sugerida, "Formato Año-Mes-Día (Ej. 2026-11-28)"),
        ("Fecha de Término (AAAA-MM-DD) *:", fecha_sugerida, "Si es de 1 día, pon la misma fecha de inicio"),
        ("Horario del Evento:", "10:00 AM a 06:00 PM", "Horario operativo del evento"),
        ("Meta de Ventas Proyectadas (Unidades):", 0, "Número entero de unidades proyectadas"),
        ("Objetivo del Evento:", "", "Ej. Generar 80 cotizaciones en piso y cerrar 15 unidades"),
        ("Alcance, Ubicación y Detalles Generales:", "", "Ej. Sucursal principal, carpa exterior, exhibición de gama")
    ]

    r_idx = 4
    for lbl, val_def, hint in campos_sec1:
        ws.row_dimensions[r_idx].height = 22
        c_lbl = ws.cell(row=r_idx, column=1, value=lbl)
        c_lbl.font = font_lbl
        c_lbl.border = borde

        ws.merge_cells(start_row=r_idx, start_column=2, end_row=r_idx, end_column=3)
        c_val = ws.cell(row=r_idx, column=2, value=val_def)
        c_val.font = font_val
        c_val.fill = fill_input
        c_val.border = borde
        ws.cell(row=r_idx, column=3).border = borde

        c_hint = ws.cell(row=r_idx, column=4, value=hint)
        c_hint.font = font_hint
        c_hint.border = borde
        r_idx += 1

    # SECCIÓN 2: LOGÍSTICA INTERNA Y DINÁMICAS (OPCIONAL)
    r_idx += 1
    ws.merge_cells(start_row=r_idx, start_column=1, end_row=r_idx, end_column=4)
    ws.cell(row=r_idx, column=1, value="2. LOGÍSTICA INTERNA Y DINÁMICAS (Opcional - Llenar solo si incluye logística)").fill = fill_slate
    ws.cell(row=r_idx, column=1).font = font_sec
    ws.row_dimensions[r_idx].height = 24
    r_idx += 1

    campos_sec2 = [
        ("¿Incluir Logística Interna en el Brief? (Sí / No):", "No", "Escribe 'Sí' si deseas incluir horarios de comida, descansos y dinámicas"),
        ("Dinámicas Internas del Evento:", "", "Ej. Pruebas de manejo, tómbola de regalos, dinámica de cierre en piso"),
        ("Horarios de Comida y Descanso del Equipo:", "", "Ej. Comida escalonada 2:00 PM a 3:00 PM, descansos de 15 min"),
        ("Elementos Externos / Edecanes / Dinámica Externa:", "", "Ej. 2 edecanes de 11:00 AM a 5:00 PM, volanteo exterior, animador")
    ]

    for lbl, val_def, hint in campos_sec2:
        ws.row_dimensions[r_idx].height = 24
        c_lbl = ws.cell(row=r_idx, column=1, value=lbl)
        c_lbl.font = font_lbl
        c_lbl.border = borde

        ws.merge_cells(start_row=r_idx, start_column=2, end_row=r_idx, end_column=3)
        c_val = ws.cell(row=r_idx, column=2, value=val_def)
        c_val.font = font_val
        c_val.fill = fill_input
        c_val.border = borde
        ws.cell(row=r_idx, column=3).border = borde

        c_hint = ws.cell(row=r_idx, column=4, value=hint)
        c_hint.font = font_hint
        c_hint.border = borde
        r_idx += 1

    # SECCIÓN 3: CHECKLIST Y PRESUPUESTO DESGLOSADO
    r_idx += 1
    ws.merge_cells(start_row=r_idx, start_column=1, end_row=r_idx, end_column=4)
    ws.cell(row=r_idx, column=1, value="3. CHECKLIST DE REQUERIMIENTOS Y PRESUPUESTO DESGLOSADO").fill = fill_navy
    ws.cell(row=r_idx, column=1).font = font_sec
    ws.row_dimensions[r_idx].height = 24
    r_idx += 1

    headers_chk = [
        "Concepto / Material / Servicio",
        "Costo Estimado ($)",
        "Nota / Estatus de Stock (Ej. Hay en stock)",
        "Responsable"
    ]
    ws.row_dimensions[r_idx].height = 22
    for c_i, h_txt in enumerate(headers_chk, 1):
        cell_h = ws.cell(row=r_idx, column=c_i, value=h_txt)
        cell_h.fill = fill_slate
        cell_h.font = font_sec
        cell_h.alignment = Alignment(horizontal="center", vertical="center")
        cell_h.border = borde
    r_idx += 1

    fila_inicio_items = r_idx
    for _ in range(20):
        ws.row_dimensions[r_idx].height = 20
        for c_i in range(1, 5):
            celda = ws.cell(row=r_idx, column=c_i, value="")
            celda.border = borde
            celda.fill = fill_input
            if c_i == 2:
                celda.number_format = '"$"#,##0.00'
        r_idx += 1
    fila_fin_items = r_idx - 1

    # Fila de Suma Total automática en Excel
    ws.row_dimensions[r_idx].height = 24
    c_tot_lbl = ws.cell(row=r_idx, column=1, value="PRESUPUESTO TOTAL COTIZADO:")
    c_tot_lbl.font = Font(bold=True, color="0F172A", size=11)
    c_tot_lbl.alignment = Alignment(horizontal="right", vertical="center")

    c_tot_val = ws.cell(row=r_idx, column=2, value=f"=SUM(B{fila_inicio_items}:B{fila_fin_items})")
    c_tot_val.font = Font(bold=True, color="0F172A", size=11)
    c_tot_val.number_format = '"$"#,##0.00'
    c_tot_val.fill = fill_note
    c_tot_val.border = borde

    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 24
    ws.column_dimensions["C"].width = 34
    ws.column_dimensions["D"].width = 42

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def _parsear_fecha_excel(val_raw, fallback_date):
    """Convierte fechas de Excel (Timestamp, DD/MM/YYYY o YYYY-MM-DD) a YYYY-MM-DD."""
    if val_raw is None or str(val_raw).strip() == "":
        return fallback_date.strftime("%Y-%m-%d")
    if isinstance(val_raw, (datetime, date, pd.Timestamp)):
        return val_raw.strftime("%Y-%m-%d")
    txt = str(val_raw).strip()
    try:
        return pd.to_datetime(txt, dayfirst="/" in txt).strftime("%Y-%m-%d")
    except Exception:
        return fallback_date.strftime("%Y-%m-%d")


def _importar_evento_desde_excel(archivo_xlsx, todas_las_marcas, marca_activa):
    """Lee la plantilla llena de Excel y devuelve el diccionario listo para guardar."""
    df = pd.read_excel(archivo_xlsx, header=None).fillna("")
    matriz = df.values.tolist()

    campos = {}
    fila_header_checklist = -1

    for idx_r, row in enumerate(matriz):
        col0 = str(row[0]).strip() if len(row) > 0 else ""
        col0_up = col0.upper()
        col1 = row[1] if len(row) > 1 else ""

        if "CONCEPTO" in col0_up and ("MATERIAL" in col0_up or "SERVICIO" in col0_up or len(row) >= 3):
            fila_header_checklist = idx_r
            break

        if col0:
            campos[col0_up] = col1

    def _buscar_campo(clave_parcial, default=""):
        for k, v in campos.items():
            if clave_parcial in k:
                return str(v).strip()
        return default

    nombre_ev = _buscar_campo("NOMBRE DEL EVENTO", "")
    if not nombre_ev:
        raise ValueError("El archivo Excel no tiene escrito el 'Nombre del Evento'.")

    marcas_raw = _buscar_campo("MARCAS ASOCIADAS", marca_activa)
    marcas_detectadas = []
    for m_part in marcas_raw.split(","):
        m_clean = m_part.strip()
        match_m = next((m for m in todas_las_marcas if m.lower() == m_clean.lower()), None)
        if match_m and match_m not in marcas_detectadas:
            marcas_detectadas.append(match_m)
    if not marcas_detectadas:
        marcas_detectadas = [marca_activa]

    solicitante = _buscar_campo("SOLICITA", "Solicitud vía Excel") or "Solicitud vía Excel"
    resp_mkt = _buscar_campo("RESPONSABLE DE MARKETING", "Área de Marketing") or "Área de Marketing"

    f_ini_raw = next((v for k, v in campos.items() if "FECHA DE INICIO" in k), "")
    f_fin_raw = next((v for k, v in campos.items() if "FECHA DE TÉRMINO" in k or "FECHA DE TERMINO" in k), "")
    fecha_ini_str = _parsear_fecha_excel(f_ini_raw, date.today() + timedelta(days=7))
    fecha_fin_str = _parsear_fecha_excel(f_fin_raw, datetime.strptime(fecha_ini_str, "%Y-%m-%d").date())

    horario = _buscar_campo("HORARIO DEL EVENTO", "Por definir") or "Por definir"

    vta_raw = _buscar_campo("META DE VENTAS", "0")
    try:
        ventas_u = int(round(float(str(vta_raw).replace(",", "").strip() or 0)))
    except Exception:
        ventas_u = 0

    objetivo = _buscar_campo("OBJETIVO DEL EVENTO", "")
    alcance = _buscar_campo("ALCANCE", "")

    flag_log = _buscar_campo("INCLUIR LOGÍSTICA", _buscar_campo("INCLUIR LOGISTICA", "No")).lower()
    din_internas = _buscar_campo("DINÁMICAS INTERNAS", _buscar_campo("DINAMICAS INTERNAS", ""))
    hor_comida = _buscar_campo("HORARIOS DE COMIDA", "")
    elem_externos = _buscar_campo("ELEMENTOS EXTERNOS", "")

    incluir_logistica = (
        flag_log in ("si", "sí", "yes", "true", "1")
        or bool(din_internas or hor_comida or elem_externos)
    )

    checklist = []
    if fila_header_checklist != -1:
        for r in range(fila_header_checklist + 1, len(matriz)):
            row = matriz[r]
            concepto = str(row[0]).strip() if len(row) > 0 else ""
            if not concepto or "PRESUPUESTO TOTAL" in concepto.upper():
                continue

            costo_raw = str(row[1]).replace("$", "").replace(",", "").strip() if len(row) > 1 else "0"
            try:
                costo_val = float(costo_raw) if costo_raw else 0.0
            except Exception:
                costo_val = 0.0

            nota_val = str(row[2]).strip() if len(row) > 2 else ""
            resp_val = str(row[3]).strip() if len(row) > 3 else ""

            checklist.append({
                "id": uuid.uuid4().hex[:6],
                "concepto": concepto,
                "costo": costo_val,
                "nota": nota_val,
                "responsable": resp_val or "Por asignar",
                "decision": "⏳ Pendiente",
                "aprobado": False,
                "pagado": False
            })

    return {
        "id": uuid.uuid4().hex[:8],
        "nombre": nombre_ev,
        "marcas": marcas_detectadas,
        "solicitante": solicitante,
        "responsable_mkt": resp_mkt,
        "etapa": ETAPAS_EVENTO[0],
        "fecha_inicio": fecha_ini_str,
        "fecha_fin": max(fecha_ini_str, fecha_fin_str),
        "horario": horario,
        "ventas_proyectadas": ventas_u,
        "objetivo": objetivo,
        "descripcion": alcance,
        "incluir_logistica": incluir_logistica,
        "dinamicas_internas": din_internas,
        "horarios_comida": hor_comida,
        "elementos_externos": elem_externos,
        "checklist": checklist
    }


# =============================================================================
# GENERADOR DE DOCUMENTO BRIEF EJECUTIVO
# =============================================================================
def _generar_html_brief(ev):
    """
    Genera el documento HTML ejecutivo del Requerimiento de Evento.
    Muestra primero el Checklist de Requerimientos y Presupuesto Desglosado,
    y en la parte inferior el Objetivo y Alcance / Logística del evento.
    """
    avance = _calcular_avance_evento(ev)
    rango_fechas = _formatear_rango_fechas(ev.get("fecha_inicio", ""), ev.get("fecha_fin", ""))
    marcas_lista = ev.get("marcas", [])
    marcas_txt = "  •  ".join(m.upper() for m in marcas_lista) if marcas_lista else "GENERAL"
    checklist = ev.get("checklist", [])
    ventas_unidades = int(round(float(ev.get("ventas_proyectadas", 0))))

    total_cotizado, total_autorizado, total_pagado = _calcular_totales_presupuesto(checklist)

    # Bloque condicional de Logística Interna y Dinámicas dentro de Alcance
    alcance_base = ev.get("descripcion", "").strip() or "Sin descripción adicional."
    logistica_html = ""
    if ev.get("incluir_logistica"):
        items_log = []
        if str(ev.get("dinamicas_internas", "")).strip():
            items_log.append(f"<li><strong>Dinámicas internas:</strong> {ev['dinamicas_internas']}</li>")
        if str(ev.get("horarios_comida", "")).strip():
            items_log.append(f"<li><strong>Horarios de comida y descanso:</strong> {ev['horarios_comida']}</li>")
        if str(ev.get("elementos_externos", "")).strip():
            items_log.append(f"<li><strong>Elementos / Personal externo (edecanes, etc.):</strong> {ev['elementos_externos']}</li>")

        if items_log:
            logistica_html = f"""
            <div style="margin-top:12px; padding-top:10px; border-top:1px dashed #CBD5E1;">
                <div style="font-size:11.5px; font-weight:800; color:#1E3A8A; text-transform:uppercase; margin-bottom:6px;">
                    Logística Interna y Dinámicas
                </div>
                <ul style="margin:0; padding-left:18px; font-size:13px; color:#1E293B; line-height:1.5;">
                    {''.join(items_log)}
                </ul>
            </div>
            """

    if not checklist:
        lista_html = "<p style='color:#64748B; font-style:italic;'>Aún no se han agregado conceptos al presupuesto del evento.</p>"
    else:
        filas_html = ""
        for idx, item in enumerate(checklist, 1):
            dec = _obtener_decision_item(item)
            nota = str(item.get("nota", "")).strip()
            nota_txt = f" <span style='color:#475569; font-style:italic;'>({nota})</span>" if nota else ""
            resp = item.get("responsable", "Por asignar") or "Por asignar"
            costo = float(item.get("costo", 0))

            if item.get("pagado"):
                icono = "✔"
                badge = "<span class='badge badge-paid'>Autorizado • Pagado</span>"
            elif dec == "✅ Aprobado":
                icono = "◉"
                badge = "<span class='badge badge-app'>Autorizado</span>"
            elif dec == "❌ No aprobado":
                icono = "✕"
                badge = "<span class='badge badge-rej'>No autorizado</span>"
            else:
                icono = "○"
                badge = "<span class='badge badge-pend'>Pendiente</span>"

            tachado = "text-decoration: line-through; opacity: 0.55;" if dec == "❌ No aprobado" else ""

            filas_html += f"""
            <tr style='{tachado}'>
                <td style='width:38px; font-weight:700; color:#1E293B;'>{idx}. {icono}</td>
                <td>
                    <strong style='color:#0F172A;'>{item.get('concepto', '')}</strong>{nota_txt}<br>
                    <small style='color:#64748B;'>Responsable: {resp}</small>
                </td>
                <td style='text-align:center;'>{badge}</td>
                <td style='text-align:right; font-weight:700; font-size:14px; color:#0F172A;'>${costo:,.2f}</td>
            </tr>
            """

        lista_html = f"""
        <table class='budget-table'>
            <thead>
                <tr>
                    <th>#</th>
                    <th>Concepto / Observación</th>
                    <th style='text-align:center;'>Estatus Junta</th>
                    <th style='text-align:right;'>Costo</th>
                </tr>
            </thead>
            <tbody>
                {filas_html}
            </tbody>
        </table>
        <div class='totals-bar'>
            <div style='color:#475569; font-size:13px;'>
                Total Pagado / Ejercido: <strong style='color:#0F172A;'>${total_pagado:,.2f}</strong>
            </div>
            <div class='totals-right'>
                <div class='tot-sub'>Presupuesto Cotizado: <strong>${total_cotizado:,.2f}</strong></div>
                <div class='tot-auth'>PRESUPUESTO AUTORIZADO: ${total_autorizado:,.2f}</div>
            </div>
        </div>
        """

    html_doc = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
    <meta charset="UTF-8">
    <title>Requerimiento - {ev.get('nombre', 'Evento')}</title>
    <style>
        body {{
            background-color: #E2E8F0;
            font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 28px;
            color: #1E293B;
        }}
        .sheet {{
            max-width: 880px;
            margin: 0 auto;
            background-color: #FFFFFF;
            border-radius: 16px;
            padding: 38px 44px;
            box-shadow: 0 10px 28px rgba(15, 23, 42, 0.12);
            border-top: 8px solid #0F172A;
        }}
        .doc-label {{
            text-align: center;
            font-size: 11px;
            letter-spacing: 2.5px;
            text-transform: uppercase;
            color: #64748B;
            font-weight: 700;
            margin-bottom: 6px;
        }}
        .brands-hero {{
            text-align: center;
            font-size: 27px;
            font-weight: 800;
            color: #0F172A;
            letter-spacing: 0.8px;
            margin: 0 0 6px 0;
            padding: 10px 16px;
            background-color: #F1F5F9;
            border-radius: 10px;
            border: 1px solid #CBD5E1;
        }}
        h1.event-title {{
            font-size: 24px;
            font-weight: 700;
            color: #1E3A8A;
            text-align: center;
            margin: 8px 0 20px 0;
        }}
        .pills-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            justify-content: center;
            margin-bottom: 24px;
        }}
        .pill-outline {{
            border: 1.5px solid #334155;
            color: #0F172A;
            background: #FFFFFF;
            padding: 7px 16px;
            border-radius: 8px;
            font-size: 13px;
        }}
        .pill-filled {{
            background: #1E293B;
            color: #FFFFFF;
            padding: 7px 16px;
            border-radius: 8px;
            font-size: 13px;
        }}
        .kpi-hero-grid {{
            display: grid;
            grid-template-columns: 1fr 1.15fr 0.85fr;
            gap: 14px;
            margin-bottom: 22px;
        }}
        .kpi-box {{
            background-color: #F8FAFC;
            border: 1.5px solid #CBD5E1;
            border-radius: 12px;
            padding: 16px 18px;
            text-align: center;
        }}
        .kpi-box-auth {{
            background-color: #0F172A;
            border: 1.5px solid #0F172A;
            border-radius: 12px;
            padding: 16px 18px;
            text-align: center;
            color: #FFFFFF;
        }}
        .kpi-title {{
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1px;
            font-weight: 700;
            color: #64748B;
            margin-bottom: 6px;
        }}
        .kpi-box-auth .kpi-title {{
            color: #94A3B8;
        }}
        .kpi-value {{
            font-size: 24px;
            font-weight: 800;
            color: #0F172A;
        }}
        .kpi-box-auth .kpi-value {{
            font-size: 26px;
            font-weight: 800;
            color: #38BDF8;
        }}
        .checklist-box {{
            background-color: #F8FAFC;
            border: 1px solid #CBD5E1;
            border-radius: 12px;
            padding: 20px 24px;
            margin-bottom: 18px;
        }}
        .checklist-box h3 {{
            color: #0F172A;
            margin: 0 0 14px 0;
            font-size: 17px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .banner-status {{
            background-color: #1E293B;
            color: #FFFFFF;
            border-radius: 12px;
            padding: 14px 22px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 18px;
        }}
        .banner-status h3 {{
            margin: 0;
            font-size: 18px;
        }}
        .banner-status .pct {{
            font-size: 22px;
            font-weight: 800;
            color: #38BDF8;
        }}
        .grid-2 {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 18px;
            margin-bottom: 0;
        }}
        .card {{
            background-color: #F8FAFC;
            border: 1px solid #E2E8F0;
            border-radius: 12px;
            padding: 18px 20px;
        }}
        .card h3 {{
            color: #0F172A;
            margin: 0 0 8px 0;
            font-size: 16px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 1px solid #E2E8F0;
            padding-bottom: 6px;
        }}
        .card p {{
            margin: 0;
            font-size: 13.5px;
            line-height: 1.55;
            color: #334155;
        }}
        .budget-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13.5px;
        }}
        .budget-table th {{
            text-align: left;
            color: #475569;
            border-bottom: 2px solid #CBD5E1;
            padding: 8px 6px;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .budget-table td {{
            padding: 10px 6px;
            border-bottom: 1px solid #E2E8F0;
            vertical-align: middle;
        }}
        .totals-bar {{
            margin-top: 18px;
            padding-top: 14px;
            border-top: 2px solid #0F172A;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
        }}
        .totals-right {{
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 6px;
        }}
        .tot-sub {{
            font-size: 15px;
            color: #334155;
        }}
        .tot-auth {{
            background-color: #0F172A;
            color: #FFFFFF;
            padding: 10px 18px;
            border-radius: 8px;
            font-size: 18px;
            font-weight: 800;
            letter-spacing: 0.3px;
        }}
        .badge {{
            font-size: 11px;
            padding: 3px 8px;
            border-radius: 6px;
            font-weight: 600;
            display: inline-block;
        }}
        .badge-paid {{ background: #DCFCE7; color: #166534; }}
        .badge-app {{ background: #DBEAFE; color: #1E40AF; }}
        .badge-rej {{ background: #FEE2E2; color: #991B1B; }}
        .badge-pend {{ background: #E2E8F0; color: #334155; }}
        @media print {{
            body {{ background: #FFFFFF; padding: 0; }}
            .sheet {{ box-shadow: none; border: 1px solid #CBD5E1; }}
        }}
    </style>
    </head>
    <body>
        <div class="sheet">
            <div class="doc-label">Requerimiento Ejecutivo de Evento</div>
            <div class="brands-hero">{marcas_txt}</div>
            <h1 class="event-title">{ev.get('nombre', 'Brief de Evento')}</h1>

            <div class="pills-row">
                <div class="pill-outline"><strong>Solicita:</strong> {ev.get('solicitante', 'N/A')}</div>
                <div class="pill-filled"><strong>Responsable Mkt:</strong> {ev.get('responsable_mkt', 'Marketing')}</div>
                <div class="pill-filled"><strong>Fecha:</strong> {rango_fechas} &bull; {ev.get('horario', '')}</div>
            </div>

            <div class="kpi-hero-grid">
                <div class="kpi-box">
                    <div class="kpi-title">Presupuesto Cotizado</div>
                    <div class="kpi-value">${total_cotizado:,.2f}</div>
                </div>
                <div class="kpi-box-auth">
                    <div class="kpi-title">Presupuesto Autorizado</div>
                    <div class="kpi-value">${total_autorizado:,.2f}</div>
                </div>
                <div class="kpi-box">
                    <div class="kpi-title">Ventas Proyectadas</div>
                    <div class="kpi-value">{ventas_unidades} u.</div>
                </div>
            </div>

            <div class="checklist-box">
                <h3>Checklist de Requerimientos y Presupuesto Desglosado</h3>
                {lista_html}
            </div>

            <div class="banner-status">
                <div>
                    <h3>{ev.get('etapa', '')}</h3>
                    <small style="color:#CBD5E1;">Última actualización: {datetime.now().strftime('%d/%m/%Y %H:%M')}</small>
                </div>
                <div class="pct">{avance:.0f}% Avance</div>
            </div>

            <div class="grid-2">
                <div class="card">
                    <h3>Objetivo del Evento</h3>
                    <p>{ev.get('objetivo', 'Sin objetivo especificado.')}</p>
                </div>
                <div class="card">
                    <h3>Alcance y Logística</h3>
                    <p>{alcance_base}</p>
                    {logistica_html}
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return html_doc


def _render_editor_checklist_y_presupuesto(db, ev_actual, prefijo_key="int"):
    """Lista editable de requerimientos, costos, notas de stock, estatus y suma total."""
    id_ev = ev_actual["id"]
    checklist = ev_actual.setdefault("checklist", [])

    st.markdown("#### 💰 Checklist y Presupuesto Desglosado del Evento")
    st.caption("Agrega conceptos con su costo y nota (ej. *Hay en stock*). Edita precios, responsables o estatus y el presupuesto total se suma automáticamente abajo.")

    with st.container(border=True):
        add1, add2, add3, add4, add5 = st.columns([2.5, 1.3, 2, 1.8, 1.1])
        nuevo_item_nom = add1.text_input("Concepto:", placeholder="Ej. Tazas / Portagafetes / Edecán", key=f"{prefijo_key}_new_nom_{id_ev}")
        nuevo_item_costo = add2.number_input("Costo ($):", min_value=0.0, step=50.0, key=f"{prefijo_key}_new_cos_{id_ev}")
        nuevo_item_nota = add3.text_input("Nota / Stock (opcional):", placeholder="Ej. Hay en stock", key=f"{prefijo_key}_new_not_{id_ev}")
        nuevo_item_resp = add4.text_input("Responsable:", placeholder="Ej. Compras / Mkt", key=f"{prefijo_key}_new_res_{id_ev}")
        add5.write("")
        add5.write("")
        if add5.button("➕ Añadir", type="primary", key=f"{prefijo_key}_btn_add_{id_ev}", width="stretch"):
            if nuevo_item_nom.strip():
                checklist.append({
                    "id": uuid.uuid4().hex[:6],
                    "concepto": nuevo_item_nom.strip(),
                    "costo": nuevo_item_costo,
                    "nota": nuevo_item_nota.strip(),
                    "responsable": nuevo_item_resp.strip() or "Por asignar",
                    "decision": "⏳ Pendiente",
                    "aprobado": False,
                    "pagado": False
                })
                guardar_datos(db)
                st.rerun()

    if checklist:
        h1, h2, h3, h4, h5, h6, h7 = st.columns([2.3, 1.2, 1.8, 1.5, 1.6, 0.8, 0.6])
        h1.caption("**Concepto**")
        h2.caption("**Costo ($)**")
        h3.caption("**Nota / Stock**")
        h4.caption("**Responsable**")
        h5.caption("**Estatus Junta**")
        h6.caption("**Pagado**")
        h7.caption("**Quitar**")

        hubo_cambio_check = False
        for idx, item in enumerate(checklist):
            it_id = item["id"]
            c_con, c_cos, c_not, c_res, c_dec, c_pag, c_del = st.columns([2.3, 1.2, 1.8, 1.5, 1.6, 0.8, 0.6])

            con_edit = c_con.text_input("Concepto", value=item.get("concepto", ""), label_visibility="collapsed", key=f"{prefijo_key}_con_{id_ev}_{it_id}")
            if con_edit != item.get("concepto", ""):
                item["concepto"] = con_edit
                hubo_cambio_check = True

            costo_edit = c_cos.number_input("Costo", value=float(item.get("costo", 0)), min_value=0.0, step=50.0, label_visibility="collapsed", key=f"{prefijo_key}_cos_{id_ev}_{it_id}")
            if costo_edit != float(item.get("costo", 0)):
                item["costo"] = costo_edit
                hubo_cambio_check = True

            nota_edit = c_not.text_input("Nota", value=item.get("nota", ""), placeholder="Nota...", label_visibility="collapsed", key=f"{prefijo_key}_not_{id_ev}_{it_id}")
            if nota_edit != item.get("nota", ""):
                item["nota"] = nota_edit
                hubo_cambio_check = True

            resp_edit = c_res.text_input("Resp", value=item.get("responsable", ""), label_visibility="collapsed", key=f"{prefijo_key}_res_{id_ev}_{it_id}")
            if resp_edit != item.get("responsable", ""):
                item["responsable"] = resp_edit
                hubo_cambio_check = True

            dec_actual = _obtener_decision_item(item)
            dec_edit = c_dec.selectbox(
                "Decisión",
                OPCIONES_DECISION,
                index=OPCIONES_DECISION.index(dec_actual),
                label_visibility="collapsed",
                key=f"{prefijo_key}_dec_{id_ev}_{it_id}"
            )
            if dec_edit != dec_actual:
                item["decision"] = dec_edit
                item["aprobado"] = (dec_edit == "✅ Aprobado")
                if dec_edit == "❌ No aprobado":
                    item["pagado"] = False
                hubo_cambio_check = True

            pag_val = c_pag.checkbox("Pagado", value=bool(item.get("pagado", False)), label_visibility="collapsed", key=f"{prefijo_key}_pag_{id_ev}_{it_id}")
            if pag_val != bool(item.get("pagado", False)):
                item["pagado"] = pag_val
                if pag_val:
                    item["decision"] = "✅ Aprobado"
                    item["aprobado"] = True
                hubo_cambio_check = True

            if c_del.button("🗑️", key=f"{prefijo_key}_del_{id_ev}_{it_id}"):
                checklist.pop(idx)
                guardar_datos(db)
                st.rerun()

        if hubo_cambio_check:
            guardar_datos(db)
            st.rerun()

        total_cotizado, total_autorizado, total_pagado = _calcular_totales_presupuesto(checklist)
        avance_pct = _calcular_avance_evento(ev_actual)

        st.markdown("##### 🧾 Resumen del Presupuesto del Evento")
        with st.container(border=True):
            for item in checklist:
                dec = _obtener_decision_item(item)
                nota_str = f" *({item['nota']})*" if item.get("nota") else ""
                pago_str = " • 💳 Pagado" if item.get("pagado") else ""
                st.markdown(f"- **{item['concepto']}** — Costo: **${float(item.get('costo', 0)):,.2f}**{nota_str} &nbsp;|&nbsp; {dec}{pago_str}")

            st.markdown("---")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Presupuesto Cotizado", f"${total_cotizado:,.2f}")
            m2.metric("Presupuesto Autorizado", f"${total_autorizado:,.2f}")
            m3.metric("Total Pagado / Ejercido", f"${total_pagado:,.2f}")
            m4.metric("Avance Checklist", f"{avance_pct:.0f}%")
    else:
        st.info("Aún no se han agregado conceptos al presupuesto de este evento. Añade arriba ítems como tazas, portagafetes, edecanes, etc.")


def _render_calendario_anual(eventos_marca, marca_activa):
    """Renderiza una vista visual de los 12 meses del año con los eventos próximos y pasados."""
    st.markdown("### 📅 Calendario Anual de Eventos")

    anio_sel = st.selectbox("Selecciona el año a visualizar:", [2025, 2026, 2027], index=1)
    hoy = date.today()

    mapa_dias = {}
    for ev in eventos_marca:
        try:
            d1 = datetime.strptime(ev["fecha_inicio"], "%Y-%m-%d").date()
            d2 = datetime.strptime(ev["fecha_fin"], "%Y-%m-%d").date()
            cursor = d1
            while cursor <= d2:
                if cursor.year == anio_sel:
                    clave = cursor.strftime("%Y-%m-%d")
                    mapa_dias.setdefault(clave, []).append(ev)
                cursor += timedelta(days=1)
        except Exception:
            continue

    st.caption("🔵 **Azul Marino:** Evento próximo o en curso &nbsp;&nbsp;|&nbsp;&nbsp; 🟢 **Verde:** Evento realizado/pasado &nbsp;&nbsp;|&nbsp;&nbsp; 💠 **Borde celeste:** Día de hoy")

    cal = calendar.Calendar(firstweekday=0)
    for fila in range(4):
        cols = st.columns(3)
        for col_idx in range(3):
            mes = fila * 3 + col_idx + 1
            semanas = cal.monthdayscalendar(anio_sel, mes)

            html_mes = f"""
            <div style="background:#1A1C24; border:1px solid #2E3240; border-radius:12px; padding:10px; margin-bottom:12px;">
                <div style="text-align:center; font-weight:700; color:#F1F5F9; margin-bottom:6px; font-size:14px;">
                    {MESES_ES[mes]} {anio_sel}
                </div>
                <table style="width:100%; border-collapse:collapse; text-align:center; font-size:11px; color:#CBD5E1;">
                    <tr style="color:#94A3B8; border-bottom:1px solid #2E3240;">
                        <th>Lu</th><th>Ma</th><th>Mi</th><th>Ju</th><th>Vi</th><th>Sá</th><th>Do</th>
                    </tr>
            """
            for sem in semanas:
                html_mes += "<tr>"
                for dia in sem:
                    if dia == 0:
                        html_mes += "<td style='padding:4px;'></td>"
                    else:
                        fecha_celda = date(anio_sel, mes, dia)
                        clave_f = fecha_celda.strftime("%Y-%m-%d")
                        evs_dia = mapa_dias.get(clave_f, [])

                        estilo = "padding:4px; border-radius:6px;"
                        tooltip = ""
                        if fecha_celda == hoy:
                            estilo += " border:1.5px solid #38BDF8; font-weight:bold;"

                        if evs_dia:
                            nombres_ev = " | ".join(e["nombre"] for e in evs_dia)
                            tooltip = f"title='{nombres_ev}'"
                            if fecha_celda < hoy:
                                estilo += " background:#166534; color:#FFFFFF; font-weight:bold;"
                            else:
                                estilo += " background:#1E3A8A; color:#FFFFFF; font-weight:bold;"

                        html_mes += f"<td style='{estilo}' {tooltip}>{dia}</td>"
                html_mes += "</tr>"
            html_mes += "</table></div>"

            with cols[col_idx]:
                st.markdown(html_mes, unsafe_allow_html=True)

    st.markdown("---")
    c_prox, c_pas = st.columns(2)

    proximos = []
    pasados = []
    for ev in eventos_marca:
        try:
            d_fin = datetime.strptime(ev["fecha_fin"], "%Y-%m-%d").date()
            if d_fin >= hoy:
                proximos.append(ev)
            else:
                pasados.append(ev)
        except Exception:
            proximos.append(ev)

    proximos.sort(key=lambda x: x.get("fecha_inicio", ""))
    pasados.sort(key=lambda x: x.get("fecha_inicio", ""), reverse=True)

    with c_prox:
        st.markdown("#### 🚀 Próximos Eventos / En Curso")
        if not proximos:
            st.info(f"No hay eventos próximos registrados para {marca_activa}.")
        for ev in proximos:
            avance = _calcular_avance_evento(ev)
            _, ppto_auth, _ = _calcular_totales_presupuesto(ev.get("checklist", []))
            rango = _formatear_rango_fechas(ev["fecha_inicio"], ev["fecha_fin"])
            v_unid = int(round(float(ev.get("ventas_proyectadas", 0))))
            with st.container(border=True):
                st.markdown(f"**{ev['nombre']}** ({ev['etapa']})")
                st.caption(f"📅 {rango} • ⏰ {ev.get('horario', '')}")
                st.caption(f"🏢 Marcas: {', '.join(ev.get('marcas', []))} • 💰 Autorizado: **${ppto_auth:,.2f}** • 🎯 Meta: **{v_unid} u.** • Avance: **{avance}%**")

    with c_pas:
        st.markdown("#### 🏁 Eventos Pasados")
        if not pasados:
            st.caption("Aún no hay eventos pasados en el historial.")
        for ev in pasados:
            _, ppto_auth, _ = _calcular_totales_presupuesto(ev.get("checklist", []))
            rango = _formatear_rango_fechas(ev["fecha_inicio"], ev["fecha_fin"])
            v_unid = int(round(float(ev.get("ventas_proyectadas", 0))))
            with st.container(border=True):
                st.markdown(f"**{ev['nombre']}** ({ev['etapa']})")
                st.caption(f"📅 {rango} • 💰 Autorizado: **${ppto_auth:,.2f}** • Meta: **{v_unid} unidades**")


def render_portal_externo():
    """Respaldo por compatibilidad si se accede vía parámetro URL."""
    render()


# =============================================================================
# VISTA PRINCIPAL DENTRO DE LA PLATAFORMA DE MARKETING
# =============================================================================
def render():
    db = st.session_state.db
    marca_activa = db["marca_activa"]
    todas_las_marcas = list(db["marcas"].keys())

    st.subheader(f"🎪 Gestión y Requerimientos de Eventos — {marca_activa}")

    if "eventos" not in db:
        db["eventos"] = []

    if "borrador_items_evento" not in st.session_state:
        st.session_state.borrador_items_evento = []

    # =========================================================================
    # BLOQUE SUPERIOR: DESCARGAR PLANTILLA EXCEL Y SUBIR PLANTILLA LLENA
    # =========================================================================
    with st.container(border=True):
        st.markdown("**📊 Solicitud Externa vía Hoja de Cálculo (Excel)**")
        st.caption("Descarga la plantilla en Excel, envíala para que la llenen con sus requerimientos y costos, y súbela aquí para cargar el evento automáticamente.")

        ex_c1, ex_c2 = st.columns([1.2, 2.3], gap="medium")

        with ex_c1:
            st.write("")
            plantilla_bytes = _generar_plantilla_excel_bytes(marca_activa, todas_las_marcas)
            st.download_button(
                label="📥 1. Descargar Plantilla Excel",
                data=plantilla_bytes,
                file_name=f"Plantilla_Evento_{marca_activa.replace(' ', '_')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch"
            )

        with ex_c2:
            archivo_excel_subido = st.file_uploader(
                "📤 2. Subir Plantilla de Excel llena (.xlsx):",
                type=["xlsx"],
                key=f"up_excel_evento_{marca_activa}"
            )
            if archivo_excel_subido is not None:
                if st.button("🚀 Importar Evento desde Excel", type="primary", key=f"btn_imp_excel_{marca_activa}"):
                    try:
                        evento_importado = _importar_evento_desde_excel(
                            archivo_excel_subido,
                            todas_las_marcas,
                            marca_activa
                        )
                        db["eventos"].append(evento_importado)
                        guardar_datos(db)
                        st.success(f"✅ Evento '{evento_importado['nombre']}' importado con {len(evento_importado['checklist'])} concepto(s) de presupuesto.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"No se pudo importar el Excel: {e}")

    eventos_marca = [ev for ev in db["eventos"] if marca_activa in ev.get("marcas", [])]

    vista = st.radio(
        "Sección de Eventos:",
        ["📋 Requerimientos, Checklist y Presupuesto", "📅 Calendario Anual de Eventos"],
        horizontal=True
    )

    st.markdown("---")

    if vista.startswith("📅"):
        _render_calendario_anual(eventos_marca, marca_activa)
        return

    # =========================================================================
    # SECCIÓN 1: CREAR NUEVO REQUERIMIENTO MANUAL (CON LOGÍSTICA CONDICIONAL)
    # =========================================================================
    mantener_abierto = (len(eventos_marca) == 0) or (len(st.session_state.borrador_items_evento) > 0)

    with st.expander("➕ Crear Nuevo Requerimiento de Evento (Iniciar Borrador)", expanded=mantener_abierto):
        c1, c2 = st.columns(2)
        nombre_ev = c1.text_input("Nombre del evento:", placeholder="Ej. Rodada Nocturna / Open House Fin de Mes", key="new_ev_nom")
        marcas_ev = c2.multiselect(
            "Marcas asociadas a este evento:",
            todas_las_marcas,
            default=[marca_activa],
            help="Si seleccionas varias marcas, el evento aparecerá automáticamente al consultar cualquiera de ellas.",
            key="new_ev_marcas"
        )

        c3, c4, c5 = st.columns(3)
        solicitante_ev = c3.text_input("¿Quién lo solicita?", placeholder="Ej. Gerencia de Ventas / Dirección", key="new_ev_sol")
        resp_mkt_ev = c4.text_input("Responsable Marketing:", value="Área de Marketing", key="new_ev_resp")
        etapa_inicial = c5.selectbox("Etapa inicial:", ETAPAS_EVENTO, index=0, key="new_ev_etapa")

        f1, f2, f3, f4 = st.columns(4)
        fecha_ini = f1.date_input("Fecha de inicio:", value=date.today() + timedelta(days=7), key="new_ev_fi")
        fecha_fin = f2.date_input("Fecha de término:", value=date.today() + timedelta(days=7), key="new_ev_ff")
        horario_ev = f3.text_input("Horario del evento:", placeholder="Ej. 10:00 AM a 06:00 PM", key="new_ev_hor")
        ventas_proy_ev = f4.number_input("Ventas proyectadas (unidades):", min_value=0, step=1, key="new_ev_vta")

        obj_ev = st.text_area("Objetivo del evento:", height=75, placeholder="Ej. Generar 80 cotizaciones en piso y cerrar 15 unidades durante el fin de semana...", key="new_ev_obj")
        desc_ev = st.text_area("Alcance, ubicación y detalles generales:", height=75, placeholder="Ej. Sucursal principal, carpa exterior, exhibición de modelos nuevos...", key="new_ev_desc")

        # --- APARTADO CONDICIONAL DE LOGÍSTICA INTERNA Y DINÁMICAS ---
        incluir_log_new = st.checkbox(
            "📋 Incluir detalles de logística interna y dinámicas del evento (comidas, descansos, edecanes, dinámica externa)",
            value=False,
            key="new_ev_inc_log"
        )

        din_internas_new = ""
        hor_comida_new = ""
        elem_externos_new = ""

        if incluir_log_new:
            with st.container(border=True):
                st.markdown("**⚙️ Logística Interna y Dinámicas del Evento**")
                din_internas_new = st.text_area(
                    "Dinámicas internas del evento:",
                    height=65,
                    placeholder="Ej. Pruebas de manejo en circuito controlado, tómbola de regalos por cotización, dinámica de cierre en piso...",
                    key="new_ev_din_int"
                )
                l_c1, l_c2 = st.columns(2)
                hor_comida_new = l_c1.text_area(
                    "Horarios de comida y descanso:",
                    height=65,
                    placeholder="Ej. Turno comida escalonado 2:00 PM a 3:00 PM (Grupo A) y 3:00 PM a 4:00 PM (Grupo B), descansos de 15 min...",
                    key="new_ev_hor_com"
                )
                elem_externos_new = l_c2.text_area(
                    "Elementos externos / Edecanes / Dinámica externa:",
                    height=65,
                    placeholder="Ej. 2 edecanes de 11:00 AM a 5:00 PM, volanteo en crucero principal, perifoneo y animador...",
                    key="new_ev_elem_ext"
                )

        # Listado de requerimientos y costos dentro del borrador
        st.markdown("---")
        st.markdown("**💰 Lista de Requerimientos y Costos del Evento (Borrador)**")
        st.caption("Agrega aquí los materiales o servicios que se necesitarán para sumar el presupuesto estimado antes de guardar.")

        b1, b2, b3, b4, b5 = st.columns([2.5, 1.3, 2, 1.8, 1.1])
        borr_nom = b1.text_input("Concepto:", placeholder="Ej. Tazas / Portagafetes / Edecán", key="borr_it_nom")
        borr_cos = b2.number_input("Costo ($):", min_value=0.0, step=50.0, key="borr_it_cos")
        borr_not = b3.text_input("Nota / Stock:", placeholder="Ej. Hay en stock", key="borr_it_not")
        borr_res = b4.text_input("Responsable:", placeholder="Ej. Compras / Mkt", key="borr_it_res")
        b5.write("")
        b5.write("")
        if b5.button("➕ Agregar", key="btn_add_borr_item", width="stretch"):
            if borr_nom.strip():
                st.session_state.borrador_items_evento.append({
                    "id": uuid.uuid4().hex[:6],
                    "concepto": borr_nom.strip(),
                    "costo": borr_cos,
                    "nota": borr_not.strip(),
                    "responsable": borr_res.strip() or "Por asignar",
                    "decision": "⏳ Pendiente",
                    "aprobado": False,
                    "pagado": False
                })
                st.rerun()
            else:
                st.warning("Escribe el nombre del concepto antes de agregarlo.")

        if st.session_state.borrador_items_evento:
            with st.container(border=True):
                suma_borr = 0.0
                for idx_b, it_b in enumerate(st.session_state.borrador_items_evento):
                    suma_borr += float(it_b["costo"])
                    col_bi1, col_bi2 = st.columns([5, 1])
                    nota_b = f" *({it_b['nota']})*" if it_b["nota"] else ""
                    col_bi1.write(f"**{idx_b + 1}. {it_b['concepto']}** — Costo: **${it_b['costo']:,.2f}**{nota_b} | Resp: {it_b['responsable']}")
                    if col_bi2.button("🗑️", key=f"del_borr_it_{it_b['id']}"):
                        st.session_state.borrador_items_evento.pop(idx_b)
                        st.rerun()
                st.markdown(f"**Presupuesto Total Cotizado en Borrador: `${suma_borr:,.2f}`**")

        st.markdown("---")
        if st.button("💾 Guardar Borrador de Requerimiento", type="primary"):
            if not nombre_ev.strip():
                st.warning("Escribe el nombre del evento.")
            elif not marcas_ev:
                st.warning("Asocia al menos una marca al evento.")
            elif fecha_fin < fecha_ini:
                st.warning("La fecha de término no puede ser anterior a la fecha de inicio.")
            else:
                nuevo_evento = {
                    "id": uuid.uuid4().hex[:8],
                    "nombre": nombre_ev.strip(),
                    "marcas": marcas_ev,
                    "solicitante": solicitante_ev.strip() or "No especificado",
                    "responsable_mkt": resp_mkt_ev.strip() or "Marketing",
                    "etapa": etapa_inicial,
                    "fecha_inicio": fecha_ini.strftime("%Y-%m-%d"),
                    "fecha_fin": fecha_fin.strftime("%Y-%m-%d"),
                    "horario": horario_ev.strip() or "Por definir",
                    "ventas_proyectadas": int(ventas_proy_ev),
                    "objetivo": obj_ev.strip(),
                    "descripcion": desc_ev.strip(),
                    "incluir_logistica": incluir_log_new,
                    "dinamicas_internas": din_internas_new.strip() if incluir_log_new else "",
                    "horarios_comida": hor_comida_new.strip() if incluir_log_new else "",
                    "elementos_externos": elem_externos_new.strip() if incluir_log_new else "",
                    "checklist": list(st.session_state.borrador_items_evento)
                }
                db["eventos"].append(nuevo_evento)
                guardar_datos(db)
                st.session_state.borrador_items_evento = []
                st.success(f"Requerimiento '{nombre_ev}' guardado correctamente.")
                st.rerun()

    # =========================================================================
    # SECCIÓN 2: SEGUIMIENTO, EDICIÓN Y PRESUPUESTO DESGLOSADO ABAJO
    # =========================================================================
    if not eventos_marca:
        st.info(f"No hay eventos guardados aún para **{marca_activa}**. Sube una plantilla Excel o llena los datos arriba.")
        return

    st.markdown("### 📌 Seguimiento y Actualización de Eventos")

    opciones_ev = {
        f"{ev['nombre']} — {_formatear_rango_fechas(ev['fecha_inicio'], ev['fecha_fin'])} [{ev['etapa']}]": ev["id"]
        for ev in eventos_marca
    }
    sel_label = st.selectbox("Selecciona el evento a gestionar:", list(opciones_ev.keys()))
    id_ev_activo = opciones_ev[sel_label]

    ev_actual = next(e for e in db["eventos"] if e["id"] == id_ev_activo)
    avance_pct = _calcular_avance_evento(ev_actual)
    ventas_unidades = int(round(float(ev_actual.get("ventas_proyectadas", 0))))

    act1, act2, act3 = st.columns([2, 1.5, 1])
    idx_etapa = ETAPAS_EVENTO.index(ev_actual["etapa"]) if ev_actual.get("etapa") in ETAPAS_EVENTO else 0
    nueva_etapa = act1.selectbox("Etapa actual del evento:", ETAPAS_EVENTO, index=idx_etapa, key=f"etapa_{id_ev_activo}")
    if nueva_etapa != ev_actual.get("etapa"):
        ev_actual["etapa"] = nueva_etapa
        guardar_datos(db)
        st.rerun()

    html_brief = _generar_html_brief(ev_actual)
    act2.download_button(
        label="📥 Descargar Brief Actualizado",
        data=html_brief.encode("utf-8"),
        file_name=f"Requerimiento_{ev_actual['nombre'].replace(' ', '_')}.html",
        mime="text/html",
        width="stretch",
        help="Descarga el documento ejecutivo actualizado. Puedes abrirlo e imprimirlo como PDF."
    )

    if act3.button("🗑️ Eliminar Evento", key=f"del_ev_{id_ev_activo}", width="stretch"):
        db["eventos"] = [e for e in db["eventos"] if e["id"] != id_ev_activo]
        guardar_datos(db)
        st.rerun()

    st.progress(min(avance_pct / 100.0, 1.0), text=f"Progreso general del evento: {avance_pct:.0f}% • Meta de ventas: {ventas_unidades} unidades")

    # Edición de datos generales + logística condicional
    with st.expander("✏️ Editar Datos Generales / Alcance y Logística del Evento", expanded=False):
        ed1, ed2 = st.columns(2)
        ev_actual["nombre"] = ed1.text_input("Nombre del evento:", value=ev_actual["nombre"], key=f"ed_nom_{id_ev_activo}")
        marcas_validas = [m for m in ev_actual.get("marcas", []) if m in todas_las_marcas]
        ev_actual["marcas"] = ed2.multiselect("Marcas asociadas:", todas_las_marcas, default=marcas_validas, key=f"ed_mar_{id_ev_activo}")

        ed3, ed4, ed5 = st.columns(3)
        ev_actual["solicitante"] = ed3.text_input("Solicitante:", value=ev_actual.get("solicitante", ""), key=f"ed_sol_{id_ev_activo}")
        ev_actual["responsable_mkt"] = ed4.text_input("Responsable Mkt:", value=ev_actual.get("responsable_mkt", ""), key=f"ed_res_{id_ev_activo}")
        ev_actual["horario"] = ed5.text_input("Horario:", value=ev_actual.get("horario", ""), key=f"ed_hor_{id_ev_activo}")

        ed6, ed7, ed8 = st.columns(3)
        d_ini_cur = datetime.strptime(ev_actual["fecha_inicio"], "%Y-%m-%d").date()
        d_fin_cur = datetime.strptime(ev_actual["fecha_fin"], "%Y-%m-%d").date()
        n_ini = ed6.date_input("Fecha inicio:", value=d_ini_cur, key=f"ed_fi_{id_ev_activo}")
        n_fin = ed7.date_input("Fecha fin:", value=d_fin_cur, key=f"ed_ff_{id_ev_activo}")
        ev_actual["fecha_inicio"] = n_ini.strftime("%Y-%m-%d")
        ev_actual["fecha_fin"] = max(n_ini, n_fin).strftime("%Y-%m-%d")
        ev_actual["ventas_proyectadas"] = ed8.number_input("Ventas proyectadas (unidades):", min_value=0, value=ventas_unidades, step=1, key=f"ed_vta_{id_ev_activo}")

        ev_actual["objetivo"] = st.text_area("Objetivo:", value=ev_actual.get("objetivo", ""), key=f"ed_obj_{id_ev_activo}")
        ev_actual["descripcion"] = st.text_area("Alcance, ubicación y detalles generales:", value=ev_actual.get("descripcion", ""), key=f"ed_des_{id_ev_activo}")

        inc_log_edit = st.checkbox(
            "📋 Incluir detalles de logística interna y dinámicas en Alcance",
            value=bool(ev_actual.get("incluir_logistica", False)),
            key=f"ed_inc_log_{id_ev_activo}"
        )
        ev_actual["incluir_logistica"] = inc_log_edit

        if inc_log_edit:
            ev_actual["dinamicas_internas"] = st.text_area(
                "Dinámicas internas del evento:",
                value=ev_actual.get("dinamicas_internas", ""),
                height=65,
                key=f"ed_din_int_{id_ev_activo}"
            )
            el1, el2 = st.columns(2)
            ev_actual["horarios_comida"] = el1.text_area(
                "Horarios de comida y descanso:",
                value=ev_actual.get("horarios_comida", ""),
                height=65,
                key=f"ed_hor_com_{id_ev_activo}"
            )
            ev_actual["elementos_externos"] = el2.text_area(
                "Elementos externos / Edecanes / Dinámica externa:",
                value=ev_actual.get("elementos_externos", ""),
                height=65,
                key=f"ed_elem_ext_{id_ev_activo}"
            )

        if st.button("💾 Guardar Cambios Generales", key=f"save_ed_{id_ev_activo}"):
            guardar_datos(db)
            st.success("Datos generales actualizados.")
            st.rerun()

    st.markdown("---")
    _render_editor_checklist_y_presupuesto(db, ev_actual, prefijo_key="int")

    st.markdown("---")
    with st.expander("👁️ Vista Previa del Requerimiento (Formato Brief Ejecutivo)", expanded=True):
        st.components.v1.html(html_brief, height=840, scrolling=True)