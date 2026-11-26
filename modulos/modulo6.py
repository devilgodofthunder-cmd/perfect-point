# modulos/modulo6.py
import io
import os
import re
import json
import uuid
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import pandas as pd
import streamlit as st

try:
    import plotly.express as px
    import plotly.graph_objects as go
    PLOTLY_INSTALLED = True
except ImportError:
    PLOTLY_INSTALLED = False

from google import genai
from storage import guardar_datos
from modulos.modulo3 import _convertir_url_sheet_a_csv, _obtener_bytes_imagen, _es_video
from modulos.modulo5 import (
    _extraer_sheet_id,
    _descargar_hoja_cruda,
    _extraer_datos_zona_autoestrena,
    _extraer_datos_grafica_contenido,
    _calcular_salud_inversion,
    _clave_orden_mes,
    _es_zona_autoestrena,
    _normalizar_texto
)

CARPETA_ALMACEN = "almacen_creativo_files"
os.makedirs(CARPETA_ALMACEN, exist_ok=True)

EXTENSIONES_BOVEDA = [
    "mp4", "mov", "avi", "webm",
    "pdf",
    "png", "jpg", "jpeg", "webp",
    "xlsx", "xls", "csv",
    "docx", "doc", "pptx", "txt"
]

PALETA_CARPETAS = [
    ("#0F766E", "#CCFBF1"),  # Teal
    ("#D97706", "#FEF3C7"),  # Ámbar
    ("#4F46E5", "#E0E7FF"),  # Índigo
    ("#E11D48", "#FFE4E6"),  # Coral / Carmesí
    ("#059669", "#D1FAE5"),  # Esmeralda
    ("#7C3AED", "#EDE9FE"),  # Violeta
    ("#0284C7", "#E0F2FE"),  # Azul Cielo
]

MESES_NUM_A_ES = {
    1: "ENERO", 2: "FEBRERO", 3: "MARZO", 4: "ABRIL",
    5: "MAYO", 6: "JUNIO", 7: "JULIO", 8: "AGOSTO",
    9: "SEPTIEMBRE", 10: "OCTUBRE", 11: "NOVIEMBRE", 12: "DICIEMBRE"
}


def _obtener_api_key(db):
    """Obtiene la API Key de Gemini desde entorno, secrets o sesión."""
    key_env = os.getenv("GEMINI_API_KEY", "").strip()
    if key_env:
        return key_env
    try:
        key_sec = str(st.secrets.get("GEMINI_API_KEY", "")).strip()
        if key_sec:
            return key_sec
    except Exception:
        pass
    return str(db.get("gemini_api_key", "")).strip()


def _obtener_icono_archivo(nombre_archivo):
    """Devuelve un ícono descriptivo según la extensión del archivo."""
    ext = os.path.splitext(str(nombre_archivo).lower())[1]
    if ext in (".xlsx", ".xls", ".csv"):
        return "📊"
    if ext in (".docx", ".doc", ".txt"):
        return "📝"
    if ext == ".pdf":
        return "📕"
    if ext in (".pptx", ".ppt"):
        return "📽️"
    if ext in (".mp4", ".mov", ".avi", ".webm"):
        return "🎬"
    if ext in (".png", ".jpg", ".jpeg", ".webp"):
        return "🖼️"
    return "📎"


def _etiqueta_enlace_externo(url):
    """Identifica automáticamente si el enlace es Google Sheets, Google Docs, Drive, Canva, etc."""
    u = str(url).lower().strip()
    if "docs.google.com/spreadsheets" in u:
        return "📊 Abrir Google Sheets"
    if "docs.google.com/document" in u:
        return "📝 Abrir Google Docs"
    if "docs.google.com/presentation" in u:
        return "📽️ Abrir Google Slides"
    if "drive.google.com" in u:
        return "📁 Abrir Google Drive"
    if "canva.com" in u:
        return "🎨 Abrir en Canva"
    if "youtube.com" in u or "youtu.be" in u:
        return "▶️ Ver en YouTube"
    return "🔗 Abrir Enlace Externo"


def _cargar_fuente_pdf(size, bold=False):
    """Carga tipografía TrueType limpia (Windows/Linux) con respaldo automático."""
    rutas_bold = [
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    ]
    rutas_reg = [
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    ]
    candidatos = rutas_bold if bold else rutas_reg
    for ruta in candidatos:
        if os.path.exists(ruta):
            try:
                return ImageFont.truetype(ruta, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def _envolver_texto_pil(draw, texto, font, max_width):
    """Divide un párrafo en líneas que quepan dentro del ancho máximo en píxeles."""
    palabras = str(texto).split()
    if not palabras:
        return []
    lineas = []
    linea_actual = palabras[0]
    for palabra in palabras[1:]:
        prueba = f"{linea_actual} {palabra}"
        bbox = draw.textbbox((0, 0), prueba, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            linea_actual = prueba
        else:
            lineas.append(linea_actual)
            linea_actual = palabra
    lineas.append(linea_actual)
    return lineas


def _dibujar_pagina_kpi_marca_pil(marca_nombre, mes_etiqueta, info_marca):
    """
    Renderiza en alta resolución (1600 x 1160 px) una página ejecutiva de KPI Dashboard
    para exportarla dentro del PDF consolidado.
    """
    W, H = 1600, 1160
    img = Image.new("RGB", (W, H), "#FFFFFF")
    draw = ImageDraw.Draw(img)

    f_title = _cargar_fuente_pdf(44, bold=True)
    f_sub = _cargar_fuente_pdf(17, bold=True)
    f_pill = _cargar_fuente_pdf(11, bold=True)
    f_kpi_lbl = _cargar_fuente_pdf(13, bold=True)
    f_kpi_val = _cargar_fuente_pdf(28, bold=True)
    f_sec_title = _cargar_fuente_pdf(15, bold=True)
    f_body = _cargar_fuente_pdf(14, bold=False)
    f_body_b = _cargar_fuente_pdf(14, bold=True)
    f_small = _cargar_fuente_pdf(12, bold=False)
    f_small_b = _cargar_fuente_pdf(12, bold=True)
    f_ring = _cargar_fuente_pdf(22, bold=True)

    embudo = info_marca.get("embudo", {})
    costos = info_marca.get("costos", {})
    score = int(info_marca.get("score", 0))
    estado_salud = info_marca.get("estado_salud", "")
    justif = info_marca.get("justif_mercado", "")
    vendedores = info_marca.get("vendedores", [])
    contenidos = info_marca.get("contenidos", [])
    es_zae = info_marca.get("es_zae", False)

    alcance = int(embudo.get("Alcance", 0))
    leads = int(embudo.get("Resultados (WhatsApp)", 0))
    citas = int(embudo.get("Citas Asistidas", 0))
    ventas = int(embudo.get("Ventas Concretadas", 0))
    inversion = float(costos.get("Inversion", 0.0))
    cpl = float(costos.get("CPL", 0.0))
    cpac = float(costos.get("CPAC", 0.0))
    cac = float(costos.get("CAC", 0.0))
    ef_cierre = (ventas / citas * 100) if citas > 0 else 0.0

    # Encabezado superior
    draw.text((48, 34), "KPI DASHBOARD", fill="#0F766E", font=f_title)
    draw.text((50, 88), f"{marca_nombre.upper()}  |  PERIODO: {mes_etiqueta}", fill="#334155", font=f_sub)
    draw.line([(48, 122), (W - 48, 122)], fill="#E2E8F0", width=2)

    pasos = [
        ("ALC", "#F59E0B", "#64748B", "ALCANCE"),
        ("WA", "#0D9488", "#0D9488", "LEADS WA"),
        ("CIT", "#EF4444", "#EF4444", "CITAS"),
        ("VTA", "#F59E0B", "#F59E0B", "VENTAS"),
        ("$$$", "#3B82F6", "#3B82F6", "COSTOS"),
        ("OK", "#10B981", "#10B981", "SALUD"),
    ]
    start_x_steps = 920
    for idx_s, (sigla, c_circ, c_pill, lbl_p) in enumerate(pasos):
        cx = start_x_steps + idx_s * 108
        cy = 58
        draw.ellipse([cx - 28, cy - 28, cx + 28, cy + 28], fill=c_circ, outline="#F1F5F9", width=3)
        bb = draw.textbbox((0, 0), sigla, font=f_small_b)
        draw.text((cx - (bb[2] - bb[0]) // 2, cy - 8), sigla, fill="#FFFFFF", font=f_small_b)
        draw.rounded_rectangle([cx - 42, cy + 34, cx + 42, cy + 54], radius=5, fill=c_pill)
        bb2 = draw.textbbox((0, 0), lbl_p, font=f_pill)
        draw.text((cx - (bb2[2] - bb2[0]) // 2, cy + 37), lbl_p, fill="#FFFFFF", font=f_pill)

    # Fila de 6 tarjetas KPI
    kpis_6 = [
        ("INVERSIÓN", f"${inversion:,.0f}", "#0F766E", "$", [45, 60, 75, 65, 90, 100]),
        ("LEADS WA", f"{leads:,}", "#F59E0B", "W", [50, 70, 60, 85, 95, 100]),
        ("CITAS ASIST.", f"{citas:,}", "#4F46E5", "C", [40, 65, 80, 70, 85, 95]),
        ("VENTAS", f"{ventas:,}", "#0D9488", "V", [35, 55, 70, 80, 90, 100]),
        ("CPL / CAC", f"${(cac if cac > 0 else cpl):,.2f}", "#EF4444", "!", [90, 75, 65, 60, 50, 45]),
        ("SALUD INV.", f"{score}/100", "#6366F1", "+", [50, 60, 75, 80, 90, max(score, 15)]),
    ]
    card_w = 236
    gap_k = 17
    for idx_k, (lbl_k, val_k, col_k, ico_txt, bars_h) in enumerate(kpis_6):
        x0 = 48 + idx_k * (card_w + gap_k)
        y0 = 144
        x1 = x0 + card_w
        y1 = y0 + 162
        draw.rounded_rectangle([x0, y0, x1, y1], radius=14, fill="#FFFFFF", outline="#CBD5E1", width=2)
        draw.ellipse([x0 + 16, y0 + 14, x0 + 50, y0 + 48], fill=col_k)
        draw.text((x0 + 28, y0 + 23), ico_txt, fill="#FFFFFF", font=f_small_b)
        draw.text((x0 + 60, y0 + 23), lbl_k, fill="#64748B", font=f_kpi_lbl)
        draw.text((x0 + 18, y0 + 62), val_k, fill="#0F172A", font=f_kpi_val)

        bx_start = x0 + 18
        bw = 26
        for b_i, bh in enumerate(bars_h):
            bx0 = bx_start + b_i * (bw + 8)
            by1 = y1 - 14
            by0 = by1 - int((bh / 100) * 34)
            draw.rounded_rectangle([bx0, by0, bx0 + bw, by1], radius=3, fill=col_k)

    # Sección media: 3 paneles
    y_mid0 = 330
    y_mid1 = 740

    # Panel 1: Embudo de Conversión
    p1_x0, p1_x1 = 48, 515
    draw.rounded_rectangle([p1_x0, y_mid0, p1_x1, y_mid1], radius=14, fill="#FFFFFF", outline="#CBD5E1", width=2)
    draw.rectangle([p1_x0 + 18, y_mid0 + 18, p1_x0 + 24, y_mid0 + 38], fill="#0F766E")
    draw.text((p1_x0 + 34, y_mid0 + 19), "EMBUDO DE CONVERSIÓN", fill="#0F172A", font=f_sec_title)

    w_alc = 100
    w_lea = max(18, int((leads / alcance) * 100)) if alcance > 0 else 65
    w_cit = max(14, int((citas / leads) * 80)) if leads > 0 else 40
    w_ven = max(10, int((ventas / leads) * 70)) if leads > 0 else 25

    emb_items = [
        ("Alcance", f"{alcance:,}", w_alc, "#1E3A8A"),
        ("Resultados (WhatsApp)", f"{leads:,}", w_lea, "#2563EB"),
        ("Citas Asistidas", f"{citas:,}", w_cit, "#0D9488"),
        ("Ventas Concretadas", f"{ventas:,}", w_ven, "#10B981"),
    ]
    max_bar_w = (p1_x1 - p1_x0) - 44
    for idx_e, (e_nom, e_val, e_pct, e_col) in enumerate(emb_items):
        ey = y_mid0 + 66 + idx_e * 82
        draw.text((p1_x0 + 22, ey), e_nom, fill="#1E293B", font=f_body_b)
        bb_v = draw.textbbox((0, 0), e_val, font=f_body_b)
        draw.text((p1_x1 - 22 - (bb_v[2] - bb_v[0]), ey), e_val, fill="#0F172A", font=f_body_b)
        bar_w = max(24, int((e_pct / 100) * max_bar_w))
        cx_panel = (p1_x0 + p1_x1) // 2
        draw.rounded_rectangle(
            [cx_panel - bar_w // 2, ey + 26, cx_panel + bar_w // 2, ey + 52],
            radius=8,
            fill=e_col
        )

    # Panel 2: Contenido Más Efectivo
    p2_x0, p2_x1 = 535, 1085
    draw.rounded_rectangle([p2_x0, y_mid0, p2_x1, y_mid1], radius=14, fill="#FFFFFF", outline="#CBD5E1", width=2)
    draw.rectangle([p2_x0 + 18, y_mid0 + 18, p2_x0 + 24, y_mid0 + 38], fill="#0F766E")
    draw.text((p2_x0 + 34, y_mid0 + 19), "CONTENIDO MÁS EFECTIVO (TOP ANUNCIOS)", fill="#0F172A", font=f_sec_title)

    draw.text((p2_x0 + 22, y_mid0 + 56), "Anuncio", fill="#64748B", font=f_small_b)
    draw.text((p2_x0 + 275, y_mid0 + 56), "Res.", fill="#64748B", font=f_small_b)
    draw.text((p2_x0 + 335, y_mid0 + 56), "Impacto", fill="#64748B", font=f_small_b)
    draw.text((p2_x1 - 75, y_mid0 + 56), "CPR", fill="#64748B", font=f_small_b)
    draw.line([(p2_x0 + 20, y_mid0 + 78), (p2_x1 - 20, y_mid0 + 78)], fill="#E2E8F0", width=1)

    if contenidos:
        top_ads = sorted(contenidos, key=lambda x: x.get("Resultados", 0), reverse=True)[:5]
        max_r = max((a.get("Resultados", 0) for a in top_ads), default=1) or 1
        for idx_a, ad in enumerate(top_ads):
            ay = y_mid0 + 92 + idx_a * 60
            nom_ad = str(ad.get("Nombre del Anuncio", ""))[:26]
            res_ad = int(ad.get("Resultados", 0))
            cpr_ad = float(ad.get("Costo / Res.", 0))
            draw.text((p2_x0 + 22, ay), nom_ad, fill="#1E293B", font=f_body_b)
            draw.text((p2_x0 + 275, ay), f"{res_ad:,}", fill="#0F172A", font=f_body_b)

            draw.rounded_rectangle([p2_x0 + 335, ay + 4, p2_x0 + 445, ay + 16], radius=5, fill="#E2E8F0")
            imp_w = max(8, int((res_ad / max_r) * 110))
            draw.rounded_rectangle([p2_x0 + 335, ay + 4, p2_x0 + 335 + imp_w, ay + 16], radius=5, fill="#0D9488")

            cpr_str = f"${cpr_ad:,.2f}"
            bb_c = draw.textbbox((0, 0), cpr_str, font=f_body)
            draw.text((p2_x1 - 22 - (bb_c[2] - bb_c[0]), ay), cpr_str, fill="#475569", font=f_body)
            draw.line([(p2_x0 + 20, ay + 42), (p2_x1 - 20, ay + 42)], fill="#F1F5F9", width=1)
    else:
        draw.text((p2_x0 + 130, y_mid0 + 190), "Sin detalle de anuncios en este periodo", fill="#64748B", font=f_body)

    # Panel 3: Vendedores o Costos Unitarios
    p3_x0, p3_x1 = 1105, W - 48
    draw.rounded_rectangle([p3_x0, y_mid0, p3_x1, y_mid1], radius=14, fill="#FFFFFF", outline="#CBD5E1", width=2)
    draw.rectangle([p3_x0 + 18, y_mid0 + 18, p3_x0 + 24, y_mid0 + 38], fill="#0F766E")

    if es_zae and vendedores:
        draw.text((p3_x0 + 34, y_mid0 + 19), "EFECTIVIDAD VENDEDORES (META 50%)", fill="#0F172A", font=f_sec_title)
        for idx_v, v in enumerate(vendedores[:5]):
            vy = y_mid0 + 72 + idx_v * 62
            ef_v = float(v.get("Efectividad (%)", 0))
            col_ef = "#10B981" if ef_v >= 50.0 else "#EF4444"
            draw.text((p3_x0 + 22, vy), str(v.get("Vendedor", ""))[:16], fill="#1E293B", font=f_body_b)
            cierres_txt = f"{v.get('Vendidos', 0)}/{v.get('Asignados / Asistidos', 0)} cierres"
            draw.text((p3_x0 + 195, vy), cierres_txt, fill="#64748B", font=f_body)
            ef_txt = f"{ef_v:.1f}%"
            bb_ef = draw.textbbox((0, 0), ef_txt, font=f_body_b)
            draw.text((p3_x1 - 22 - (bb_ef[2] - bb_ef[0]), vy), ef_txt, fill=col_ef, font=f_body_b)
            draw.line([(p3_x0 + 20, vy + 40), (p3_x1 - 20, vy + 40)], fill="#F1F5F9", width=1)
    else:
        draw.text((p3_x0 + 34, y_mid0 + 19), "COSTOS UNITARIOS Y RENTABILIDAD", fill="#0F172A", font=f_sec_title)
        filas_c = [
            ("Costo por Lead (CPL)", f"${cpl:,.2f}", "#0F172A"),
            ("Costo por Cita (CPAC)", f"${cpac:,.2f}", "#0F172A"),
            ("CAC Publicitario", f"${cac:,.2f}", "#0D9488"),
        ]
        for idx_c, (c_lbl, c_val, c_col) in enumerate(filas_c):
            cy_row = y_mid0 + 85 + idx_c * 95
            draw.text((p3_x0 + 24, cy_row), c_lbl, fill="#475569", font=f_body_b)
            bb_cv = draw.textbbox((0, 0), c_val, font=f_kpi_val)
            draw.text((p3_x1 - 24 - (bb_cv[2] - bb_cv[0]), cy_row - 6), c_val, fill=c_col, font=f_kpi_val)
            if idx_c < 2:
                draw.line([(p3_x0 + 22, cy_row + 54), (p3_x1 - 22, cy_row + 54)], fill="#E2E8F0", width=1)

    # Sección inferior: Key Insights + Goals Progress
    y_bot0 = 762
    y_bot1 = H - 36

    b1_x0, b1_x1 = 48, 1020
    draw.rounded_rectangle([b1_x0, y_bot0, b1_x1, y_bot1], radius=14, fill="#FFFFFF", outline="#CBD5E1", width=2)
    draw.rectangle([b1_x0 + 18, y_bot0 + 18, b1_x0 + 24, y_bot0 + 38], fill="#0F766E")
    draw.text((b1_x0 + 34, y_bot0 + 19), "KEY INSIGHTS & JUSTIFICACIÓN DE MERCADO", fill="#0F172A", font=f_sec_title)

    draw.rounded_rectangle([b1_x0 + 18, y_bot0 + 54, b1_x0 + 455, y_bot1 - 18], radius=10, fill="#F8FAFC")
    draw.text((b1_x0 + 30, y_bot0 + 64), estado_salud, fill="#0F766E", font=f_body_b)
    lineas_j = _envolver_texto_pil(draw, justif, f_small, 410)
    for l_i, linea in enumerate(lineas_j[:11]):
        draw.text((b1_x0 + 30, y_bot0 + 88 + l_i * 19), linea, fill="#334155", font=f_small)

    mejor_ad = sorted(contenidos, key=lambda x: x.get("Resultados", 0), reverse=True)[0]["Nombre del Anuncio"] if contenidos else "N/A"
    draw.rounded_rectangle([b1_x0 + 470, y_bot0 + 54, b1_x0 + 710, y_bot1 - 18], radius=10, fill="#F8FAFC")
    draw.text((b1_x0 + 482, y_bot0 + 64), "Anuncio Líder", fill="#D97706", font=f_body_b)
    lineas_ad = _envolver_texto_pil(draw, f"El creativo con mayor tracción en el periodo fue {mejor_ad}.", f_small, 215)
    for l_i, linea in enumerate(lineas_ad[:9]):
        draw.text((b1_x0 + 482, y_bot0 + 90 + l_i * 20), linea, fill="#334155", font=f_small)

    draw.rounded_rectangle([b1_x0 + 725, y_bot0 + 54, b1_x1 - 18, y_bot1 - 18], radius=10, fill="#F8FAFC")
    draw.text((b1_x0 + 737, y_bot0 + 64), "Enfoque Comercial", fill="#DC2626", font=f_body_b)
    txt_enf = f"CPL: ${cpl:,.2f}\nCPAC: ${cpac:,.2f}\nCAC: ${cac:,.2f}"
    for l_i, linea in enumerate(txt_enf.split("\n")):
        draw.text((b1_x0 + 737, y_bot0 + 96 + l_i * 26), linea, fill="#1E293B", font=f_body_b)

    b2_x0, b2_x1 = 1040, W - 48
    draw.rounded_rectangle([b2_x0, y_bot0, b2_x1, y_bot1], radius=14, fill="#FFFFFF", outline="#CBD5E1", width=2)
    draw.rectangle([b2_x0 + 18, y_bot0 + 18, b2_x0 + 24, y_bot0 + 38], fill="#0F766E")
    draw.text((b2_x0 + 34, y_bot0 + 19), "GOALS PROGRESS", fill="#0F172A", font=f_sec_title)

    vendedores_meta = sum(1 for v in vendedores if v.get("Efectividad (%)", 0) >= 50)
    pct_vend_ok = int((vendedores_meta / len(vendedores)) * 100) if vendedores else int(min(ef_cierre * 2, 100))

    anillos = [
        (f"{score}%", "#0F766E", "Salud Inversión"),
        (f"{ef_cierre:.0f}%", "#F59E0B", "Cierre Cita→Venta"),
        (f"{pct_vend_ok}%", "#4F46E5", "Meta Vendedores"),
    ]
    for idx_r, (r_val, r_col, r_lbl) in enumerate(anillos):
        rcx = b2_x0 + 95 + idx_r * 162
        rcy = y_bot0 + 150
        draw.ellipse([rcx - 52, rcy - 52, rcx + 52, rcy + 52], outline=r_col, width=10)
        bb_r = draw.textbbox((0, 0), r_val, font=f_ring)
        draw.text((rcx - (bb_r[2] - bb_r[0]) // 2, rcy - 13), r_val, fill=r_col, font=f_ring)
        bb_rl = draw.textbbox((0, 0), r_lbl, font=f_small_b)
        draw.text((rcx - (bb_rl[2] - bb_rl[0]) // 2, rcy + 66), r_lbl, fill="#475569", font=f_small_b)

    return img


def _generar_pdf_consolidado_mes(mes_etiqueta, datos_marcas_mes):
    """Combina las páginas KPI Dashboard de todas las marcas en un único PDF descargable."""
    paginas_img = []
    for marca_nom, info_m in datos_marcas_mes.items():
        pagina = _dibujar_pagina_kpi_marca_pil(marca_nom, mes_etiqueta, info_m)
        paginas_img.append(pagina.convert("RGB"))

    if not paginas_img:
        return None

    buffer_pdf = io.BytesIO()
    paginas_img[0].save(
        buffer_pdf,
        format="PDF",
        resolution=150.0,
        save_all=True,
        append_images=paginas_img[1:]
    )
    buffer_pdf.seek(0)
    return buffer_pdf.getvalue()


def _recopilar_datos_consolidados_por_mes(db):
    """Consolida los resultados de TODAS las marcas organizados por título de mes."""
    todas_las_marcas = list(db.get("marcas", {}).keys())
    cfg_res = db.get("config_resultados", {})
    historial_anual = cfg_res.get("historial_anual", {})
    url_maestra = cfg_res.get("url_archivo_maestro", "")
    sheet_id = _extraer_sheet_id(url_maestra)

    df_segunda_etapa = None
    df_grafica_cont = None
    if sheet_id:
        try:
            df_segunda_etapa = _descargar_hoja_cruda(sheet_id, "SEGUNDA ETAPA ZONA AUTOESTRENA")
        except Exception:
            pass
        try:
            df_grafica_cont = _descargar_hoja_cruda(sheet_id, "GRAFICA CONTENIDO")
        except Exception:
            pass

    datos_zae_live = _extraer_datos_zona_autoestrena(df_segunda_etapa) if df_segunda_etapa is not None else {}

    consolidado = {}

    for marca in todas_las_marcas:
        es_zae = _es_zona_autoestrena(marca)
        datos_cont_marca = _extraer_datos_grafica_contenido(df_grafica_cont, marca) if df_grafica_cont is not None else {}
        hist_m = historial_anual.get(marca, {})

        meses_marca = set(hist_m.keys()) | set(datos_cont_marca.keys())
        if es_zae:
            meses_marca |= set(datos_zae_live.keys())

        for mes_lbl in meses_marca:
            if es_zae and mes_lbl in datos_zae_live:
                embudo = datos_zae_live[mes_lbl]["embudo"]
                costos = datos_zae_live[mes_lbl]["costos"]
                vendedores = datos_zae_live[mes_lbl]["vendedores"]
            elif mes_lbl in datos_cont_marca:
                embudo = datos_cont_marca[mes_lbl]["embudo"]
                costos = datos_cont_marca[mes_lbl]["costos"]
                vendedores = []
            elif mes_lbl in hist_m:
                h_row = hist_m[mes_lbl]
                embudo = {
                    "Alcance": h_row.get("Alcance", 0),
                    "Resultados (WhatsApp)": h_row.get("Resultados", 0),
                    "Citas Asistidas": h_row.get("Citas", 0),
                    "Ventas Concretadas": h_row.get("Ventas", 0)
                }
                costos = {
                    "Inversion": h_row.get("Inversion", 0),
                    "CPL": h_row.get("CPL", 0),
                    "CPAC": h_row.get("CPAC", 0),
                    "CAC": h_row.get("CAC", 0)
                }
                vendedores = []
            else:
                continue

            contenidos = datos_cont_marca.get(mes_lbl, {}).get("contenidos", [])
            score, estado_s, justif_s, _ = _calcular_salud_inversion(embudo, costos, es_zae=es_zae, marca_nombre=marca)

            consolidado.setdefault(mes_lbl, {})[marca] = {
                "embudo": embudo,
                "costos": costos,
                "vendedores": vendedores,
                "contenidos": contenidos,
                "score": score,
                "estado_salud": estado_s,
                "justif_mercado": justif_s,
                "es_zae": es_zae
            }

    return consolidado


def _fecha_a_mes_etiqueta(fecha_str):
    """Convierte fechas como '18/11/2026 10:00 AM' o '2026-11-24' a 'NOVIEMBRE 2026'."""
    s = str(fecha_str).strip()
    m_iso = re.search(r"(20\d{2})-(\d{2})", s)
    if m_iso:
        anio = m_iso.group(1)
        mes_n = int(m_iso.group(2))
        return f"{MESES_NUM_A_ES.get(mes_n, 'GENERAL')} {anio}"
    m_lat = re.search(r"\d{2}/(\d{2})/(20\d{2})", s)
    if m_lat:
        mes_n = int(m_lat.group(1))
        anio = m_lat.group(2)
        return f"{MESES_NUM_A_ES.get(mes_n, 'GENERAL')} {anio}"
    return "GENERAL 2026"


def _obtener_publicaciones_candidatas(db, marca_activa):
    """Reúne publicaciones desde el calendario nativo y/o el Google Sheet vinculado en Módulo 3."""
    candidatas = []
    marca_norm = _normalizar_texto(marca_activa)

    for item in db.get("calendario_nativo", {}).get(marca_activa, []):
        candidatas.append({
            "id": item.get("ID", uuid.uuid4().hex[:6]),
            "marca": marca_activa,
            "copy": item.get("COPY_FACEBOOK") or item.get("COPY_INSTAGRAM") or "",
            "horario": item.get("HORARIO_FACEBOOK", ""),
            "mes": _fecha_a_mes_etiqueta(item.get("HORARIO_FACEBOOK", "")),
            "media": item.get("URL_IMAGEN", ""),
            "estado": item.get("ESTADO", "Pendiente")
        })

    if len(candidatas) < 5:
        url_cal = db.get("config_calendario", {}).get("google_sheet_url", "")
        if url_cal:
            csv_u = _convertir_url_sheet_a_csv(url_cal)
            if csv_u:
                try:
                    df_c = pd.read_csv(csv_u)
                    df_c.columns = [str(c).strip().upper() for c in df_c.columns]
                    if "MARCA" in df_c.columns:
                        df_m = df_c[df_c["MARCA"].astype(str).apply(_normalizar_texto) == marca_norm]
                        for idx, r in df_m.head(25).iterrows():
                            copy_txt = str(r.get("COPY_FACEBOOK", "") or r.get("COPY_INSTAGRAM", "")).strip()
                            if not copy_txt or copy_txt.lower() == "nan":
                                continue
                            horario_txt = str(r.get("HORARIO_FACEBOOK", "")).strip()
                            candidatas.append({
                                "id": f"sh_{idx}",
                                "marca": marca_activa,
                                "copy": copy_txt,
                                "horario": horario_txt,
                                "mes": _fecha_a_mes_etiqueta(horario_txt),
                                "media": str(r.get("URL_IMAGEN", "")).strip() if pd.notna(r.get("URL_IMAGEN")) else "",
                                "estado": str(r.get("ESTADO", "Pendiente")).strip()
                            })
                except Exception:
                    pass

    return candidatas


def render():
    db = st.session_state.db
    marca_activa = db.get("marca_activa", "General")
    api_key = _obtener_api_key(db)

    st.markdown("""
    <style>
        .cabinet-banner {
            background: linear-gradient(135deg, #0F172A 0%, #1E293B 55%, #0F766E 100%);
            border-radius: 16px;
            padding: 20px 26px;
            margin-bottom: 18px;
            border: 1px solid #334155;
        }
        .cabinet-banner h2 {
            margin: 0;
            color: #F8FAFC;
            font-size: 26px;
        }
        .cabinet-banner p {
            margin: 4px 0 0 0;
            color: #CBD5E1;
            font-size: 13.5px;
        }
        .folder-tab {
            display: inline-block;
            padding: 8px 18px;
            border-radius: 12px 12px 0 0;
            font-weight: 800;
            font-size: 13px;
            letter-spacing: 0.6px;
            margin-bottom: -4px;
        }
    </style>
    <div class="cabinet-banner">
        <h2>🗂️ Almacén Creativo &amp; Archivo Histórico Multi-Marca</h2>
        <p>Repositorio central organizado por mes: consolidado global en PDF, top publicaciones curadas por IA, eventos, prospección en frío y bóveda multimedia.</p>
    </div>
    """, unsafe_allow_html=True)

    almacen_db = db.setdefault("almacen_creativo", {
        "top5_curado": {},
        "prospeccion_eventos_ia": {},
        "boveda_items": []
    })

    consolidado_meses = _recopilar_datos_consolidados_por_mes(db)
    meses_eventos = {_fecha_a_mes_etiqueta(e.get("fecha_inicio", "")) for e in db.get("eventos", [])}
    meses_boveda = {b.get("mes", "") for b in almacen_db.get("boveda_items", []) if b.get("mes")}

    todos_meses_set = set(consolidado_meses.keys()) | meses_eventos | meses_boveda
    if not todos_meses_set:
        todos_meses_set = {f"{MESES_NUM_A_ES[datetime.now().month]} {datetime.now().year}"}

    meses_ordenados = sorted(list(todos_meses_set), key=_clave_orden_mes)

    c_mes1, c_mes2 = st.columns([2.5, 1.5])
    mes_activo = c_mes1.selectbox(
        "📂 Selecciona el Cajón Mensual del Archivero:",
        meses_ordenados,
        index=len(meses_ordenados) - 1,
        key="almacen_mes_selector"
    )

    idx_color = meses_ordenados.index(mes_activo) % len(PALETA_CARPETAS)
    bg_tab, fg_tab = PALETA_CARPETAS[idx_color]

    c_mes1.markdown(
        f"<div class='folder-tab' style='background:{bg_tab}; color:{fg_tab};'>📁 EXPEDIENTE MENSUAL: {mes_activo}</div>",
        unsafe_allow_html=True
    )

    c_mes2.write("")
    if c_mes2.button("🔄 Sincronizar todo el ecosistema", width="stretch"):
        st.cache_data.clear()
        st.rerun()

    st.markdown(f"<div style='height:4px; background:{bg_tab}; border-radius:4px; margin-bottom:16px;'></div>", unsafe_allow_html=True)

    sub1, sub2, sub3, sub4 = st.tabs([
        "📊 1. Consolidado Global & PDF",
        "✨ 2. Top 5 Publicaciones (Curaduría IA)",
        "🎪 3. Eventos & Prospección en Frío",
        "🎬 4. Bóveda de Videos, Hojas y Propuestas"
    ])

    # =========================================================================
    # PESTAÑA 1: CONSOLIDADO GLOBAL DE TODAS LAS MARCAS + DESCARGA PDF
    # =========================================================================
    with sub1:
        datos_mes = consolidado_meses.get(mes_activo, {})

        if not datos_mes:
            st.info(f"Aún no hay métricas guardadas para **{mes_activo}**. Ve al Módulo 5 (Resultados) y guarda o sincroniza los reportes de este mes.")
        else:
            tot_inv_global = sum(m["costos"].get("Inversion", 0) for m in datos_mes.values())
            tot_leads_global = sum(int(m["embudo"].get("Resultados (WhatsApp)", 0)) for m in datos_mes.values())
            tot_citas_global = sum(int(m["embudo"].get("Citas Asistidas", 0)) for m in datos_mes.values())
            tot_ventas_global = sum(int(m["embudo"].get("Ventas Concretadas", 0)) for m in datos_mes.values())
            salud_prom_global = int(sum(m["score"] for m in datos_mes.values()) / len(datos_mes))

            h_p1, h_p2 = st.columns([2.5, 1.3])
            h_p1.markdown(f"### 🌐 Consolidado Multi-Marca — {mes_activo}")

            pdf_bytes = _generar_pdf_consolidado_mes(mes_activo, datos_mes)
            if pdf_bytes:
                h_p2.download_button(
                    label=f"📥 Descargar PDF ({mes_activo})",
                    data=pdf_bytes,
                    file_name=f"{mes_activo.replace(' ', '_')}_RESULTADOS_GLOBALES.pdf",
                    mime="application/pdf",
                    type="primary",
                    width="stretch"
                )

            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Inversión Global", f"${tot_inv_global:,.2f}")
            k2.metric("Leads Totales (WA)", f"{tot_leads_global:,}")
            k3.metric("Citas Asistidas", f"{tot_citas_global:,}")
            k4.metric("Ventas Concretadas", f"{tot_ventas_global:,}")
            k5.metric("Salud Promedio", f"{salud_prom_global} / 100")

            filas_comp = []
            for m_nom, m_inf in datos_mes.items():
                filas_comp.append({
                    "Marca": m_nom,
                    "Alcance": int(m_inf["embudo"].get("Alcance", 0)),
                    "Leads WA": int(m_inf["embudo"].get("Resultados (WhatsApp)", 0)),
                    "Citas": int(m_inf["embudo"].get("Citas Asistidas", 0)),
                    "Ventas": int(m_inf["embudo"].get("Ventas Concretadas", 0)),
                    "Inversión ($)": round(float(m_inf["costos"].get("Inversion", 0)), 2),
                    "CPL ($)": round(float(m_inf["costos"].get("CPL", 0)), 2),
                    "CAC ($)": round(float(m_inf["costos"].get("CAC", 0)), 2),
                    "Salud": f"{m_inf['score']}/100 ({m_inf['estado_salud']})"
                })
            df_comp = pd.DataFrame(filas_comp)
            st.dataframe(df_comp, width="stretch", hide_index=True)

            if PLOTLY_INSTALLED and len(df_comp) > 0:
                g1, g2 = st.columns(2)
                with g1:
                    fig_g1 = px.bar(
                        df_comp,
                        x="Marca",
                        y="Leads WA",
                        color="Marca",
                        text="Leads WA",
                        title=f"💬 Leads Generados por Marca — {mes_activo}",
                        color_discrete_sequence=["#0F766E", "#D97706", "#4F46E5", "#E11D48"]
                    )
                    fig_g1.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False, height=340)
                    st.plotly_chart(fig_g1, use_container_width=True)

                with g2:
                    fig_g2 = px.bar(
                        df_comp,
                        x="Marca",
                        y="Inversión ($)",
                        color="Marca",
                        text_auto=".2s",
                        title=f"💰 Distribución de Inversión — {mes_activo}",
                        color_discrete_sequence=["#0F766E", "#D97706", "#4F46E5", "#E11D48"]
                    )
                    fig_g2.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False, height=340)
                    st.plotly_chart(fig_g2, use_container_width=True)

    # =========================================================================
    # PESTAÑA 2: CURADURÍA IA — TOP 5 PUBLICACIONES MÁS VISTOSAS POR MARCA
    # =========================================================================
    with sub2:
        st.markdown(f"### ✨ Top 5 Publicaciones Más Llamativas y Creativas — {marca_activa}")
        st.caption("La IA analiza el calendario de publicaciones y selecciona únicamente las **5 piezas más atractivas, creativas e ideales** para tu portafolio.")

        candidatas = _obtener_publicaciones_candidatas(db, marca_activa)

        col_cur1, col_cur2 = st.columns([2, 1])
        col_cur1.info(f"Publicaciones disponibles detectadas para **{marca_activa}**: **{len(candidatas)}**")

        if col_cur2.button("✨ Curar Top 5 Piezas con IA", type="primary", width="stretch", key=f"btn_curar_{marca_activa}"):
            if not candidatas:
                st.warning("No se encontraron publicaciones para esta marca en el Módulo 3.")
            elif not api_key:
                con_media = [c for c in candidatas if c.get("media")]
                seleccion = (con_media + candidatas)[:5]
                for s in seleccion:
                    s["razon_ia"] = "Seleccionada por contar con recurso visual listo para portafolio."
                almacen_db["top5_curado"][marca_activa] = seleccion
                guardar_datos(db)
                st.rerun()
            else:
                try:
                    with st.spinner("La IA está evaluando creatividad, gancho visual y copy para elegir el Top 5..."):
                        resumen_posts = "\n".join([
                            f"ID: {c['id']} | TieneImagen: {bool(c['media'])} | Copy: {c['copy'][:220]}"
                            for c in candidatas[:25]
                        ])
                        prompt_cur = f"""
                        Eres Director Creativo de una agencia de marketing automotriz y biker en México.
                        Analiza estas publicaciones de la marca '{marca_activa}' y selecciona EXACTAMENTE las 5 más vistosas, creativas, llamativas e ideales para mostrar en un portafolio de casos de éxito.
                        Prioriza las que tengan imagen/video y mejor gancho comercial.

                        Publicaciones:
                        {resumen_posts}

                        Responde ÚNICAMENTE con un JSON válido con esta estructura exacta (sin markdown extra):
                        [
                          {{"id": "ID_DEL_POST", "razon": "Explicación breve en 1 frase de por qué es creativa y llamativa"}}
                        ]
                        """
                        client = genai.Client(api_key=api_key)
                        resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt_cur)
                        txt_json = resp.text.strip().replace("```json", "").replace("```", "").strip()
                        elegidos_ia = json.loads(txt_json)

                        mapa_cand = {c["id"]: c for c in candidatas}
                        top5_final = []
                        for item_ia in elegidos_ia[:5]:
                            pid = str(item_ia.get("id", ""))
                            if pid in mapa_cand:
                                copia = dict(mapa_cand[pid])
                                copia["razon_ia"] = item_ia.get("razon", "Pieza destacada por creatividad y gancho.")
                                top5_final.append(copia)

                        if not top5_final:
                            top5_final = candidatas[:5]

                        almacen_db["top5_curado"][marca_activa] = top5_final
                        guardar_datos(db)
                        st.success("¡Top 5 curado y guardado en el portafolio de la marca!")
                        st.rerun()
                except Exception as e:
                    st.error(f"No se pudo completar la curaduría IA: {e}")

        top5_guardado = almacen_db.get("top5_curado", {}).get(marca_activa, [])
        if not top5_guardado:
            st.caption("Presiona **✨ Curar Top 5 Piezas con IA** para extraer automáticamente las 5 mejores muestras de esta marca.")
        else:
            for idx_p, post in enumerate(top5_guardado, 1):
                with st.container(border=True):
                    pc1, pc2 = st.columns([1.2, 2.8], gap="medium")
                    with pc1:
                        media_url = post.get("media", "")
                        if media_url:
                            if _es_video(media_url):
                                st.video(media_url)
                            else:
                                img_b = _obtener_bytes_imagen(media_url)
                                if img_b:
                                    st.image(img_b, width="stretch")
                                else:
                                    st.info("🖼️ Pieza gráfica vinculada")
                        else:
                            st.info("📝 Copy destacado")
                    with pc2:
                        st.markdown(f"**🏆 Pieza #{idx_p} — {marca_activa}** (`{post.get('mes', '')}`)")
                        if post.get("razon_ia"):
                            st.success(f"💡 **Por qué destaca:** {post['razon_ia']}")
                        st.write(post.get("copy", ""))

    # =========================================================================
    # PESTAÑA 3: EVENTOS + IDEAS DE NUEVOS EVENTOS + PROSPECCIÓN EN FRÍO
    # =========================================================================
    with sub3:
        st.markdown(f"### 🎪 Historial de Eventos y Oportunidades Comerciales — {marca_activa}")

        eventos_marca = [e for e in db.get("eventos", []) if marca_activa in e.get("marcas", [])]
        if eventos_marca:
            st.markdown("**📌 Eventos Registrados en la Plataforma**")
            for ev in eventos_marca:
                with st.container(border=True):
                    st.markdown(f"**{ev['nombre']}** — `{ev.get('etapa', '')}`")
                    st.caption(f"📅 {ev.get('fecha_inicio')} al {ev.get('fecha_fin')} • 🎯 Meta: **{ev.get('ventas_proyectadas', 0)} unidades** • Objetivo: {ev.get('objetivo', '')}")
        else:
            st.caption(f"No hay eventos previos registrados para {marca_activa} en el Módulo 4.")

        st.markdown("---")
        st.markdown("#### 🎯 Generador IA: Nuevos Eventos + Directorio de Venta en Frío (B2B / Empresas)")
        st.caption("La IA analiza el giro de tu marca y te propone **nuevos eventos estratégicos** más un listado de **giros, empresas reales, direcciones y teléfonos** en CDMX / Edomex para prospectar en frío.")

        zona_prosp = st.text_input(
            "Zona geográfica prioritaria para prospección en frío:",
            value="CDMX y Estado de México (Ecatepec, Azcapotzalco, Tlalnepantla, Vallejo, Naucalpan)",
            key=f"zona_prosp_{marca_activa}"
        )

        if st.button(f"🚀 Generar Ideas de Eventos y Prospectos en Frío para {marca_activa}", type="primary", key=f"btn_prosp_{marca_activa}"):
            if not api_key:
                st.warning("El servicio de Inteligencia Artificial no está configurado en el servidor (`GEMINI_API_KEY`).")
            else:
                try:
                    with st.spinner("Investigando oportunidades de eventos y empresas prospecto en CDMX / Edomex..."):
                        prompt_b2b = f"""
                        Actúa como Director Comercial y de Eventos B2B en México para la marca: **{marca_activa}**.
                        Contexto del negocio:
- Zona Auto Estrena / TVS Venta de Carpio: Venta y financiamiento de motocicletas y vehículos en CDMX y Edomex.
- Banda Biker: GPS, rastreo satelital, corte de corriente y accesorios para motos y flotillas.
- Lead Zone Pro: Agencia de marketing digital, generación de leads y pauta Meta Ads para negocios.
                        Zona de interés: {zona_prosp}.

                        Genera dos secciones estructuradas:
                        ### 1. 🎪 4 Nuevos Eventos de Alto Impacto Sugeridos
                        Para cada evento incluye: Nombre llamativo, Sede recomendada, Mecánica de atracción y Meta estimada de ventas.

                        ### 2. 📞 Directorio de Oportunidades para Venta en Frío (8 Empresas / Marcas Prospecto)
                        Presenta una tabla Markdown con las columnas:
                        | Giro / Sector | Empresa o Marca Prospecto | Dirección / Zona (CDMX - Edomex) | Teléfono / Contacto Público | Propuesta de Valor en Frío |

                        Incluye empresas reales reconocidas con operación en esas zonas (ej. empresas de mensajería, seguridad privada, parques industriales, flotillas de reparto, distribuidoras, concesionarios o corporativos según corresponda a {marca_activa}) con sus teléfonos corporativos públicos y direcciones de sucursal o matriz.
                        """
                        client = genai.Client(api_key=api_key)
                        resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt_b2b)
                        almacen_db["prospeccion_eventos_ia"][marca_activa] = resp.text
                        guardar_datos(db)
                        st.rerun()
                except Exception as e:
                    st.error(f"Error al generar sugerencias: {e}")

        resultado_prosp = almacen_db.get("prospeccion_eventos_ia", {}).get(marca_activa, "")
        if resultado_prosp:
            with st.container(border=True):
                st.markdown(resultado_prosp)

    # =========================================================================
    # PESTAÑA 4: BÓVEDA DE VIDEOS, HOJAS DE CÁLCULO, DOCS Y PROPUESTAS
    # =========================================================================
    with sub4:
        st.markdown(f"### 🎬 Bóveda de Videos, Hojas de Cálculo, Docs y Propuestas — `{marca_activa}`")
        st.caption("Archiva múltiples archivos de manera simultánea (Excel, CSV, Word, PDF, Videos, Imágenes) y enlaces de **Google Sheets, Google Docs, Drive o Canva**.")

        with st.expander("➕ Archivar Nuevo Proyecto, Carpeta o Propuesta (Carga Múltiple)", expanded=True):
            v1, v2, v3 = st.columns(3)
            tit_item = v1.text_input("Título del proyecto / paquete:", placeholder="Ej. ISLA PLAZA PERINORTE / Campaña Buen Fin")
            cat_item = v2.selectbox(
                "Categoría:",
                [
                    "📄 Propuesta Comercial",
                    "📊 Hoja de Cálculo / Cotización",
                    "🎬 Video / Reel",
                    "🏆 Caso de Éxito",
                    "🎨 Diseño / Campaña",
                    "📁 Proyecto Especial"
                ]
            )
            mes_item = v3.selectbox("Cajón Mensual:", meses_ordenados, index=meses_ordenados.index(mes_activo))

            v4, v5 = st.columns(2)
            archivos_bov = v4.file_uploader(
                "Subir uno o varios archivos simultáneamente (Excel, CSV, Word, PDF, Videos, Imágenes):",
                type=EXTENSIONES_BOVEDA,
                accept_multiple_files=True,
                key="up_boveda_multi_m6"
            )
            if archivos_bov:
                v4.caption(f"✅ **{len(archivos_bov)} archivo(s) seleccionados:** {', '.join([f.name for f in archivos_bov])}")

            enlaces_bov_txt = v5.text_area(
                "Enlaces de Google Sheets, Google Docs, Drive o Canva (uno por línea):",
                height=105,
                placeholder="https://docs.google.com/spreadsheets/d/...\nhttps://docs.google.com/document/d/..."
            )

            notas_bov = st.text_area("Notas, acuerdos o resultados obtenidos:", height=70, placeholder="Ej. Propuesta económica en Excel, presentación ejecutiva y renders de isla...")

            if st.button("💾 Guardar en Almacén Creativo", type="primary"):
                if not tit_item.strip():
                    st.warning("Escribe un título para archivar el proyecto.")
                else:
                    lista_archivos_guardados = []
                    if archivos_bov:
                        for f_up in archivos_bov:
                            nom_u = f"{uuid.uuid4().hex[:8]}_{f_up.name}"
                            ruta_f = os.path.join(CARPETA_ALMACEN, nom_u)
                            with open(ruta_f, "wb") as f_out:
                                f_out.write(f_up.getbuffer())
                            lista_archivos_guardados.append({
                                "nombre_original": f_up.name,
                                "ruta": ruta_f
                            })

                    lista_enlaces_guardados = [
                        ln.strip() for ln in enlaces_bov_txt.splitlines() if ln.strip()
                    ]

                    almacen_db["boveda_items"].append({
                        "id": uuid.uuid4().hex[:8],
                        "marca": marca_activa,
                        "mes": mes_item,
                        "titulo": tit_item.strip(),
                        "categoria": cat_item,
                        "archivos": lista_archivos_guardados,
                        "enlaces": lista_enlaces_guardados,
                        "notas": notas_bov.strip(),
                        "fecha_registro": datetime.now().strftime("%d/%m/%Y")
                    })
                    guardar_datos(db)
                    st.success(f"Archivado '{tit_item.strip()}' en el cajón de {mes_item} con {len(lista_archivos_guardados)} archivo(s) y {len(lista_enlaces_guardados)} enlace(s).")
                    st.rerun()

        st.markdown("---")
        filtro_cajon = st.radio(
            "Mostrar expedientes de:",
            [f"📂 Solo cajón activo ({mes_activo})", f"🗄️ Todos los cajones de {marca_activa}"],
            horizontal=True,
            key=f"filtro_bov_{marca_activa}"
        )

        if filtro_cajon.startswith("📂"):
            items_boveda = [
                it for it in almacen_db.get("boveda_items", [])
                if it.get("mes") == mes_activo and it.get("marca") == marca_activa
            ]
        else:
            items_boveda = [
                it for it in almacen_db.get("boveda_items", [])
                if it.get("marca") == marca_activa
            ]

        if not items_boveda:
            st.info(f"No hay expedientes archivados en esta vista para **{marca_activa}**.")
        else:
            for it in reversed(items_boveda):
                archivos_item = list(it.get("archivos", []))
                if not archivos_item and it.get("archivo"):
                    archivos_item = [{
                        "nombre_original": os.path.basename(it["archivo"]),
                        "ruta": it["archivo"]
                    }]

                enlaces_item = list(it.get("enlaces", []))
                if not enlaces_item and it.get("enlace"):
                    enlaces_item = [it["enlace"]]

                with st.container(border=True):
                    head_c1, head_c2 = st.columns([4, 1])
                    head_c1.markdown(f"#### {it['titulo']}  —  `{it['categoria']}`")
                    head_c1.caption(f"🏢 {it['marca']} • 📂 Cajón: **{it['mes']}** • Archivado: {it.get('fecha_registro', '')} • 📎 {len(archivos_item)} archivo(s) • 🔗 {len(enlaces_item)} enlace(s)")

                    if head_c2.button("🗑️ Eliminar", key=f"del_bov_{it['id']}", width="stretch"):
                        for a_dict in archivos_item:
                            r_del = a_dict.get("ruta", "")
                            if r_del and os.path.exists(r_del):
                                try:
                                    os.remove(r_del)
                                except Exception:
                                    pass
                        almacen_db["boveda_items"] = [x for x in almacen_db["boveda_items"] if x["id"] != it["id"]]
                        guardar_datos(db)
                        st.rerun()

                    if it.get("notas"):
                        st.write(it["notas"])

                    if enlaces_item:
                        cols_links = st.columns(min(len(enlaces_item), 3))
                        for idx_l, url_ext in enumerate(enlaces_item):
                            lbl_btn = _etiqueta_enlace_externo(url_ext)
                            cols_links[idx_l % 3].link_button(lbl_btn, url_ext, width="stretch")

                    if archivos_item:
                        cols_files = st.columns(min(len(archivos_item), 3))
                        for idx_f, a_info in enumerate(archivos_item):
                            ruta_f = a_info.get("ruta", "")
                            nom_orig = a_info.get("nombre_original", os.path.basename(ruta_f))
                            icono_f = _obtener_icono_archivo(nom_orig)
                            col_target = cols_files[idx_f % 3]

                            with col_target:
                                if ruta_f and os.path.exists(ruta_f):
                                    if _es_video(ruta_f):
                                        st.video(ruta_f)
                                    elif ruta_f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                                        st.image(ruta_f, width="stretch")

                                    with open(ruta_f, "rb") as f_dl:
                                        st.download_button(
                                            label=f"{icono_f} {nom_orig[:28]}",
                                            data=f_dl.read(),
                                            file_name=nom_orig,
                                            key=f"dl_bov_{it['id']}_{idx_f}",
                                            width="stretch"
                                        )
                                else:
                                    st.caption(f"⚠️ Archivo no encontrado: {nom_orig}")