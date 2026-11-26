# modulos/modulo5.py
import io
import json
import os
import re
import urllib.parse
from datetime import datetime, date, timedelta
import pandas as pd
import requests
import streamlit as st

try:
    import plotly.express as px
    import plotly.graph_objects as go
    PLOTLY_INSTALLED = True
except ImportError:
    PLOTLY_INSTALLED = False

from google import genai
from storage import guardar_datos

HOJAS_CONOCIDAS_DEFAULT = [
    "SEGUNDA ETAPA ZONA AUTOESTRENA",
    "GRAFICA CONTENIDO",
    "📊 DASHBOARD",
    "ZONA AUTOESTRENA",
    "TVS VENTA DE CARPIO",
    "BANDA BIKER",
    "LEAD ZONE PRO",
    "EFECTIVIDAD DE CONTENIDO"
]

MESES_ES_MAP = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
}

ORDEN_MESES_ANIO = [
    "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
    "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"
]


def _obtener_api_key(db):
    """Obtiene la API Key de Gemini desde el entorno, secrets o sesión."""
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


def _normalizar_texto(texto):
    """Normaliza nombres de marca ignorando espacios, acentos o mayúsculas."""
    if pd.isna(texto):
        return ""
    return re.sub(r"[^a-z0-9]", "", str(texto).lower())


def _es_zona_autoestrena(marca_nombre):
    m = _normalizar_texto(marca_nombre)
    return "zona" in m and "auto" in m


def _obtener_benchmark_mercado(marca_nombre):
    """
    Devuelve los parámetros de referencia (benchmarks) del mercado mexicano
    según el giro comercial de cada marca para justificar la salud de inversión.
    """
    m = _normalizar_texto(marca_nombre)
    if "zona" in m and "auto" in m:
        return {
            "sector": "Automotriz y Motocicletas Financiamiento (CDMX / Edomex)",
            "cpl_mercado": 22.0,     # Promedio Meta Ads WhatsApp automotriz MX ($18-$28)
            "cac_mercado": 650.0,    # Promedio costo por venta concretada en piso MX ($500-$1,200)
            "cierre_mercado": 15.0   # Promedio tasa cierre cita -> venta en piso automotriz (12%-17%)
        }
    elif "tvs" in m or "biker" in m or "banda" in m:
        return {
            "sector": "Motocicletas, Refacciones y Comunidad Biker (México)",
            "cpl_mercado": 18.0,     # Promedio Meta Ads retail/motos MX ($15-$25)
            "cac_mercado": 450.0,
            "cierre_mercado": 15.0
        }
    elif "lead" in m or "zone" in m:
        return {
            "sector": "Servicios B2B y Generación de Demanda (México)",
            "cpl_mercado": 45.0,     # Promedio Meta Ads servicios B2B MX ($35-$85)
            "cac_mercado": 900.0,
            "cierre_mercado": 12.0
        }
    return {
        "sector": "Comercio y Servicios Digitales (México)",
        "cpl_mercado": 25.0,
        "cac_mercado": 550.0,
        "cierre_mercado": 15.0
    }


def _extraer_sheet_id(url):
    """Obtiene el ID único del libro de Google Sheets desde cualquier enlace."""
    if not url:
        return None
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", str(url).strip())
    return match.group(1) if match else None


@st.cache_data(ttl=600, show_spinner=False)
def _obtener_mapa_pestanas(sheet_id):
    """Obtiene el diccionario {nombre_pestana: gid} directamente del libro de Google Sheets."""
    mapa = {}
    if not sheet_id:
        return mapa
    try:
        url_html = f"https://docs.google.com/spreadsheets/d/{sheet_id}/htmlview"
        resp = requests.get(url_html, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
        if resp.status_code == 200:
            bloques = re.findall(r'items\.push\(\{(.*?)\}\);', resp.text, re.DOTALL)
            for b in bloques:
                m_name = re.search(r'name:\s*"([^"]+)"', b)
                m_gid = re.search(r'gid:\s*"([0-9]+)"', b)
                if m_name and m_gid:
                    raw_name = m_name.group(1)
                    try:
                        clean_name = raw_name.encode("utf-8").decode("unicode_escape")
                    except Exception:
                        clean_name = raw_name
                    mapa[clean_name.strip()] = m_gid.group(1)
    except Exception:
        pass
    return mapa


@st.cache_data(ttl=300, show_spinner=False)
def _descargar_hoja_cruda(sheet_id, nombre_hoja):
    """Descarga la pestaña exacta celda por celda usando export?format=csv&gid=..."""
    mapa_gids = _obtener_mapa_pestanas(sheet_id)
    gid_encontrado = None

    objetivo_norm = _normalizar_texto(nombre_hoja)
    for k_name, v_gid in mapa_gids.items():
        if k_name.strip().upper() == nombre_hoja.strip().upper() or _normalizar_texto(k_name) == objetivo_norm:
            gid_encontrado = v_gid
            break

    if gid_encontrado:
        url_csv = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid_encontrado}"
    else:
        hoja_cod = urllib.parse.quote(str(nombre_hoja).strip())
        url_csv = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&headers=0&sheet={hoja_cod}"

    resp = requests.get(url_csv, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    resp.raise_for_status()
    contenido = resp.content.decode("utf-8", errors="replace")

    if contenido.lstrip().startswith("<!DOCTYPE html") or "<html" in contenido[:300].lower():
        raise PermissionError("Google Sheets devolvió una página de acceso. Verifica que el archivo esté compartido como 'Cualquier persona con el enlace: Lector'.")

    df = pd.read_csv(io.StringIO(contenido), header=None, dtype=str)
    return df.fillna("")


def _limpiar_numero(valor):
    """Convierte textos como '$271.38', '11,884' o '33.7%' a número flotante."""
    if valor is None or pd.isna(valor):
        return 0.0
    s = str(valor).strip()
    if not s or s.lower() in ("none", "nan", "sin url", "-"):
        return 0.0
    limpio = re.sub(r"[^0-9.-]", "", s)
    try:
        return float(limpio)
    except ValueError:
        return 0.0


def _clave_orden_mes(etiqueta_mes):
    """Ordena cronológicamente etiquetas como 'AGOSTO 2026', 'SEPTIEMBRE 2026', etc."""
    txt = str(etiqueta_mes).upper().strip()
    match_anio = re.search(r"(20\d{2})", txt)
    anio = int(match_anio.group(1)) if match_anio else 2026
    mes_num = 99
    for idx, m_nom in enumerate(ORDEN_MESES_ANIO, 1):
        if m_nom in txt:
            mes_num = idx
            break
    return (anio, mes_num, txt)


def _extraer_etiqueta_mes(texto):
    """Extrae la etiqueta del mes (ej. 'AGOSTO 2026') desde un título de bloque."""
    txt_up = str(texto).upper().strip()
    for m_nom in ORDEN_MESES_ANIO:
        if m_nom in txt_up:
            m_anio = re.search(r"(20\d{2})", txt_up)
            return f"{m_nom} {m_anio.group(1)}" if m_anio else m_nom
    for sep in ["-", "–", "—"]:
        if sep in txt_up:
            return txt_up.split(sep)[-1].strip()
    return txt_up


# =============================================================================
# PARSER AUTOMÁTICO 1: ZONA AUTOESTRENA (HOJA SEGUNDA ETAPA DESDE COLUMNA N)
# =============================================================================
def _extraer_datos_zona_autoestrena(df_segunda_etapa):
    """Lee a partir de la Columna N (índice 13) todos los bloques mensuales en 'SEGUNDA ETAPA ZONA AUTOESTRENA'."""
    if df_segunda_etapa is None or df_segunda_etapa.empty:
        return {}

    matriz = df_segunda_etapa.values.tolist()
    n_filas = len(matriz)
    n_cols = len(matriz[0]) if n_filas > 0 else 0

    if n_cols <= 13:
        return {}

    columnas_mes = []
    for c in range(13, n_cols):
        celda_r0 = str(matriz[0][c]).strip() if n_filas > 0 else ""
        celda_r2 = str(matriz[2][c]).strip() if n_filas > 2 else ""

        mes_etiqueta = ""
        if "[" in celda_r0 and "]" in celda_r0:
            mes_etiqueta = celda_r0.split("[")[-1].split("]")[0].strip().upper()
        elif "EMBUDO GENERAL" in celda_r2.upper() and "(" in celda_r2:
            mes_etiqueta = celda_r2.split("(")[-1].split(")")[0].strip().upper()

        if mes_etiqueta:
            columnas_mes.append((c, mes_etiqueta))

    resultados_por_mes = {}

    for col_ini, mes_etiqueta in columnas_mes:
        embudo = {
            "Impresiones": 0.0,
            "Alcance": 0.0,
            "Resultados (WhatsApp)": 0.0,
            "Citas Asistidas": 0.0,
            "Ventas Concretadas": 0.0,
            "Conv. Lead a Asistencia (%)": 0.0,
            "Efectividad Cierre (%)": 0.0
        }
        vendedores = []
        costos = {
            "Inversion": 0.0,
            "CPL": 0.0,
            "CPAC": 0.0,
            "CAC": 0.0
        }

        seccion = None
        for r in range(n_filas):
            etiqueta = str(matriz[r][col_ini]).strip() if col_ini < len(matriz[r]) else ""
            etiqueta_up = etiqueta.upper()
            val_c1 = matriz[r][col_ini + 1] if (col_ini + 1) < len(matriz[r]) else ""

            if not etiqueta:
                continue

            if "1. EMBUDO" in etiqueta_up:
                seccion = "EMBUDO"
                continue
            elif "2. EFECTIVIDAD POR ASESOR" in etiqueta_up:
                seccion = "ASESORES"
                continue
            elif "3. COSTOS PUBLICITARIOS" in etiqueta_up:
                seccion = "COSTOS"
                continue

            if seccion == "EMBUDO":
                if "IMPRESIONES" in etiqueta_up:
                    embudo["Impresiones"] = _limpiar_numero(val_c1)
                elif "ALCANCE" in etiqueta_up:
                    embudo["Alcance"] = _limpiar_numero(val_c1)
                elif "RESULTADOS" in etiqueta_up or "WHATSAPP" in etiqueta_up:
                    embudo["Resultados (WhatsApp)"] = _limpiar_numero(val_c1)
                elif "CITAS ASISTIDAS" in etiqueta_up:
                    embudo["Citas Asistidas"] = _limpiar_numero(val_c1)
                elif "VENTAS CONCRETADAS" in etiqueta_up:
                    embudo["Ventas Concretadas"] = _limpiar_numero(val_c1)
                elif "CONV." in etiqueta_up:
                    embudo["Conv. Lead a Asistencia (%)"] = _limpiar_numero(val_c1)
                elif "EFECTIVIDAD CIERRE" in etiqueta_up:
                    embudo["Efectividad Cierre (%)"] = _limpiar_numero(val_c1)

            elif seccion == "ASESORES":
                if etiqueta_up == "ASESOR":
                    continue
                asist = _limpiar_numero(val_c1)
                vend = _limpiar_numero(matriz[r][col_ini + 2]) if (col_ini + 2) < len(matriz[r]) else 0.0
                ef_raw = _limpiar_numero(matriz[r][col_ini + 3]) if (col_ini + 3) < len(matriz[r]) else 0.0
                ef_pct = ef_raw * 100 if (0 < ef_raw <= 1.0 and "%" not in str(matriz[r][col_ini + 3])) else ef_raw
                if ef_pct == 0 and asist > 0:
                    ef_pct = round((vend / asist) * 100, 1)

                vendedores.append({
                    "Vendedor": etiqueta,
                    "Asignados / Asistidos": int(asist),
                    "Vendidos": int(vend),
                    "Efectividad (%)": round(ef_pct, 1),
                    "Cumple Meta 50%": "✅ Sí" if ef_pct >= 50.0 else "⚠️ Bajo Meta"
                })

            elif seccion == "COSTOS":
                if "INVERSI" in etiqueta_up:
                    costos["Inversion"] = _limpiar_numero(val_c1)
                elif "CPL" in etiqueta_up or "COSTO POR LEAD" in etiqueta_up:
                    costos["CPL"] = _limpiar_numero(val_c1)
                elif "CPAC" in etiqueta_up or "COSTO POR CITA" in etiqueta_up:
                    costos["CPAC"] = _limpiar_numero(val_c1)
                elif "CAC" in etiqueta_up:
                    costos["CAC"] = _limpiar_numero(val_c1)

        resultados_por_mes[mes_etiqueta] = {
            "embudo": embudo,
            "vendedores": vendedores,
            "costos": costos
        }

    return resultados_por_mes


# =============================================================================
# PARSER AUTOMÁTICO 2: GRAFICA CONTENIDO (COLUMNA B Y COLUMNA J POR MARCA)
# =============================================================================
def _extraer_datos_grafica_contenido(df_grafica_contenido, marca_objetivo):
    """Escanea 'GRAFICA CONTENIDO' buscando todos los bloques mensuales de la marca activa."""
    if df_grafica_contenido is None or df_grafica_contenido.empty:
        return {}

    matriz = df_grafica_contenido.values.tolist()
    n_filas = len(matriz)
    n_cols = len(matriz[0]) if n_filas > 0 else 0
    marca_norm = _normalizar_texto(marca_objetivo)

    bloques_marca = []
    for r in range(n_filas):
        for c in range(n_cols):
            val = str(matriz[r][c]).strip()
            val_up = val.upper()
            if val_up.startswith("REPORTE ") and "EJECUTIVO" not in val_up:
                val_norm = _normalizar_texto(val_up)
                if marca_norm and marca_norm in val_norm:
                    mes_etiqueta = _extraer_etiqueta_mes(val_up)
                    bloques_marca.append((r, c, mes_etiqueta))

    resultados_por_mes = {}

    for r_inicio, c_base, mes_etiqueta in bloques_marca:
        r_fin = n_filas - 1
        for r_scan in range(r_inicio + 1, n_filas):
            celda_scan = str(matriz[r_scan][c_base]).strip().upper() if c_base < len(matriz[r_scan]) else ""
            if celda_scan.startswith("REPORTE "):
                r_fin = r_scan - 1
                break

        col_anuncio = c_base + 1
        if (r_inicio + 1) < n_filas:
            hdr_c0 = str(matriz[r_inicio + 1][c_base]).strip().upper() if c_base < len(matriz[r_inicio + 1]) else ""
            if "NOMBRE DEL ANUNCIO" in hdr_c0:
                col_anuncio = c_base

        offset_cols = col_anuncio - (c_base + 1)

        contenidos = []
        for r in range(r_inicio + 1, r_fin + 1):
            if col_anuncio >= len(matriz[r]):
                continue
            nom_anuncio = str(matriz[r][col_anuncio]).strip()
            if not nom_anuncio or nom_anuncio.upper() == "NOMBRE DEL ANUNCIO":
                continue

            c_conj = c_base + 2 + offset_cols
            c_res = c_base + 3 + offset_cols
            c_cpr = c_base + 4 + offset_cols
            c_imp = c_base + 5 + offset_cols
            c_alc = c_base + 6 + offset_cols
            c_cre = c_base + 7 + offset_cols

            conjunto = str(matriz[r][c_conj]).strip() if c_conj < len(matriz[r]) else ""
            res_ad = _limpiar_numero(matriz[r][c_res]) if c_res < len(matriz[r]) else 0.0
            cpr_ad = _limpiar_numero(matriz[r][c_cpr]) if c_cpr < len(matriz[r]) else 0.0
            imp_ad = _limpiar_numero(matriz[r][c_imp]) if c_imp < len(matriz[r]) else 0.0
            alc_ad = _limpiar_numero(matriz[r][c_alc]) if c_alc < len(matriz[r]) else 0.0
            creat_ad = str(matriz[r][c_cre]).strip() if c_cre < len(matriz[r]) else ""

            contenidos.append({
                "Nombre del Anuncio": nom_anuncio,
                "Conjunto": conjunto,
                "Resultados": int(res_ad),
                "Costo / Res.": round(cpr_ad, 2),
                "Impresiones": int(imp_ad),
                "Alcance": int(alc_ad),
                "Creatividad": creat_ad if creat_ad else "Ver Anuncio"
            })

        col_j = c_base + 9 + offset_cols
        embudo = {
            "Impresiones": 0.0,
            "Alcance": 0.0,
            "Resultados (WhatsApp)": 0.0,
            "Citas Asistidas": 0.0,
            "Ventas Concretadas": 0.0
        }
        costos = {
            "Inversion": 0.0,
            "CPL": 0.0,
            "CPAC": 0.0,
            "CAC": 0.0
        }

        sub_seccion = None
        for r in range(r_inicio + 1, r_fin + 1):
            if col_j >= len(matriz[r]):
                continue
            etiqueta_j = str(matriz[r][col_j]).strip()
            etiqueta_j_up = etiqueta_j.upper()
            val_k = matriz[r][col_j + 1] if (col_j + 1) < len(matriz[r]) else ""

            if not etiqueta_j:
                continue

            if "EMBUDO" in etiqueta_j_up:
                sub_seccion = "EMBUDO"
                continue
            elif "3. COSTOS" in etiqueta_j_up or "COSTOS PUBLICITARIOS" in etiqueta_j_up or "RENTABILIDAD" in etiqueta_j_up:
                sub_seccion = "COSTOS"
                continue

            if sub_seccion == "EMBUDO":
                if "IMPRESIONES" in etiqueta_j_up:
                    embudo["Impresiones"] = _limpiar_numero(val_k)
                elif "ALCANCE" in etiqueta_j_up:
                    embudo["Alcance"] = _limpiar_numero(val_k)
                elif "RESULTADOS" in etiqueta_j_up or "WHATSAPP" in etiqueta_j_up:
                    embudo["Resultados (WhatsApp)"] = _limpiar_numero(val_k)
                elif "CITAS ASISTIDAS" in etiqueta_j_up:
                    embudo["Citas Asistidas"] = _limpiar_numero(val_k)
                elif "VENTAS CONCRETADAS" in etiqueta_j_up:
                    embudo["Ventas Concretadas"] = _limpiar_numero(val_k)

            elif sub_seccion == "COSTOS":
                if "INVERSI" in etiqueta_j_up:
                    costos["Inversion"] = _limpiar_numero(val_k)
                elif "CPL" in etiqueta_j_up or "COSTO POR LEAD" in etiqueta_j_up:
                    costos["CPL"] = _limpiar_numero(val_k)
                elif "CPAC" in etiqueta_j_up or "COSTO POR CITA" in etiqueta_j_up:
                    costos["CPAC"] = _limpiar_numero(val_k)
                elif "CAC" in etiqueta_j_up:
                    costos["CAC"] = _limpiar_numero(val_k)

        resultados_por_mes[mes_etiqueta] = {
            "embudo": embudo,
            "costos": costos,
            "contenidos": contenidos
        }

    return resultados_por_mes


# =============================================================================
# CÁLCULO DE SALUD JUSTIFICADA CON BENCHMARKS DEL MERCADO MEXICANO
# =============================================================================
def _calcular_salud_inversion(embudo, costos, es_zae, marca_nombre=""):
    """
    Evalúa de 0 a 100 qué tan saludable es la inversión comparando los resultados
    reales contra los benchmarks del mercado mexicano del mismo giro comercial.
    """
    bench = _obtener_benchmark_mercado(marca_nombre)
    inversion = costos.get("Inversion", 0.0)
    leads = embudo.get("Resultados (WhatsApp)", 0.0)
    citas = embudo.get("Citas Asistidas", 0.0)
    ventas = embudo.get("Ventas Concretadas", 0.0)
    cpl = costos.get("CPL", 0.0)
    cac = costos.get("CAC", 0.0)

    cpl_mkt = bench["cpl_mercado"]
    cac_mkt = bench["cac_mercado"]
    cierre_mkt = bench["cierre_mercado"]

    if inversion <= 0 and leads <= 0:
        return 0, "Sin inversión registrada", "No hay gasto ni resultados reportados en este periodo.", bench

    if es_zae:
        if ventas <= 0 and inversion > 0:
            justif = f"Gasto de ${inversion:,.2f} sin cierres registrados frente a un CAC promedio del sector de ${cac_mkt:,.2f}."
            return 22, "🔴 Crítico (Sin cierres)", justif, bench

        ahorro_cac_pct = ((cac_mkt - cac) / cac_mkt) * 100 if cac_mkt > 0 else 0
        ahorro_cpl_pct = ((cpl_mkt - cpl) / cpl_mkt) * 100 if cpl_mkt > 0 and cpl > 0 else 0
        tasa_cierre_real = (ventas / citas * 100) if citas > 0 else 0.0

        if cac <= 250:
            score = 92
            estado = "🟢 Líder vs Mercado"
        elif cac <= 350:
            score = 80
            estado = "🟢 Inversión Saludable"
        elif cac <= cac_mkt:
            score = 64
            estado = "🟡 En Rango de Mercado"
        else:
            score = 34
            estado = "🔴 Por Encima del Mercado"

        if tasa_cierre_real >= cierre_mkt * 1.5:
            score = min(score + 5, 98)
        elif 0 < tasa_cierre_real < cierre_mkt * 0.7:
            score = max(score - 6, 15)

        comp_cac = f"{abs(ahorro_cac_pct):.0f}% más barato" if ahorro_cac_pct >= 0 else f"{abs(ahorro_cac_pct):.0f}% más caro"
        comp_cpl = f"{abs(ahorro_cpl_pct):.0f}% menor" if ahorro_cpl_pct >= 0 else f"{abs(ahorro_cpl_pct):.0f}% mayor"

        justif = (
            f"Vs. Mercado ({bench['sector']}): Tu CAC (${cac:,.2f}) es {comp_cac} que el promedio del sector (${cac_mkt:,.2f}), "
            f"tu CPL (${cpl:,.2f}) es {comp_cpl} que el estándar (${cpl_mkt:,.2f}) y tu cierre en piso ({tasa_cierre_real:.1f}%) "
            f"supera el {cierre_mkt:.0f}% habitual de la industria."
        )
        return score, estado, justif, bench
    else:
        if leads <= 0 and inversion > 0:
            justif = f"Gasto de ${inversion:,.2f} sin conversaciones frente a un CPL promedio de mercado de ${cpl_mkt:,.2f}."
            return 20, "🔴 Crítico (Sin leads)", justif, bench

        ahorro_cpl_pct = ((cpl_mkt - cpl) / cpl_mkt) * 100 if cpl_mkt > 0 else 0

        if cpl <= cpl_mkt * 0.65:
            score = 94
            estado = "🟢 Líder vs Mercado"
        elif cpl <= cpl_mkt * 1.15:
            score = 82
            estado = "🟢 Inversión Saludable"
        elif cpl <= cpl_mkt * 2.0:
            score = 58
            estado = "🟡 Salud Moderada"
        else:
            score = 30
            estado = "🔴 CPL Sobre Mercado"

        comp_cpl = f"{abs(ahorro_cpl_pct):.0f}% más económico" if ahorro_cpl_pct >= 0 else f"{abs(ahorro_cpl_pct):.0f}% más alto"
        justif = (
            f"Vs. Mercado ({bench['sector']}): Tu CPL de ${cpl:,.2f} es {comp_cpl} que el promedio de la competencia "
            f"(${cpl_mkt:,.2f} MXN/lead), logrando {int(leads):,} resultados con ${inversion:,.2f} invertidos."
        )
        return score, estado, justif, bench


def _render_grafica_embudo(embudo, titulo):
    etapas = ["Alcance", "Resultados (WhatsApp)", "Citas Asistidas", "Ventas Concretadas"]
    valores = [
        embudo.get("Alcance", 0),
        embudo.get("Resultados (WhatsApp)", 0),
        embudo.get("Citas Asistidas", 0),
        embudo.get("Ventas Concretadas", 0)
    ]
    fig = go.Figure(go.Funnel(
        y=etapas,
        x=valores,
        textposition="inside",
        textinfo="value+percent initial",
        marker={"color": ["#1E3A8A", "#2563EB", "#0D9488", "#10B981"]}
    ))
    fig.update_layout(
        title=titulo,
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=370,
        margin=dict(l=20, r=20, t=50, b=20)
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_grafica_costos_barras(costos, titulo):
    conceptos = [
        "Costo por Lead / WhatsApp (CPL)",
        "Costo por Cita Asistida (CPAC)",
        "CAC Publicitario (Por Venta)"
    ]
    valores = [
        costos.get("CPL", 0.0),
        costos.get("CPAC", 0.0),
        costos.get("CAC", 0.0)
    ]
    fig = go.Figure(go.Bar(
        x=conceptos,
        y=valores,
        text=[f"${v:,.2f}" for v in valores],
        textposition="auto",
        marker_color=["#3B82F6", "#F59E0B", "#EF4444"]
    ))
    fig.update_layout(
        title=titulo,
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        yaxis_title="Costo ($ MXN)",
        height=390,
        margin=dict(l=20, r=20, t=50, b=20)
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_medidor_salud(score, estado_txt, justificacion_txt, embudo, costos, bench, es_zae):
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        number={"suffix": " / 100", "font": {"size": 30}},
        title={"text": f"Salud de la Inversión<br><span style='font-size:13px;color:#94A3B8'>{estado_txt}</span>"},
        gauge={
            "axis": {"range": [0, 100], "tickwidth": 1},
            "bar": {"color": "#38BDF8"},
            "steps": [
                {"range": [0, 49], "color": "rgba(239, 68, 68, 0.35)"},
                {"range": [49, 74], "color": "rgba(245, 158, 11, 0.35)"},
                {"range": [74, 100], "color": "rgba(16, 185, 129, 0.35)"}
            ],
            "threshold": {
                "line": {"color": "#FFFFFF", "width": 3},
                "thickness": 0.8,
                "value": score
            }
        }
    ))
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        height=270,
        margin=dict(l=25, r=25, t=60, b=10)
    )
    st.plotly_chart(fig, use_container_width=True)

    with st.container(border=True):
        st.caption(f"📊 **Justificación vs. Mercado ({bench['sector']})**")
        st.write(justificacion_txt)
        c_b1, c_b2 = st.columns(2)
        c_b1.caption(f"• **Tu CPL:** `${costos.get('CPL', 0):,.2f}` vs Mercado: `${bench['cpl_mercado']:,.2f}`")
        if es_zae:
            citas = embudo.get("Citas Asistidas", 0)
            ventas = embudo.get("Ventas Concretadas", 0)
            cierre_real = (ventas / citas * 100) if citas > 0 else 0.0
            c_b2.caption(f"• **Tu CAC:** `${costos.get('CAC', 0):,.2f}` vs Mercado: `${bench['cac_mercado']:,.2f}` | Cierre: **{cierre_real:.1f}%** vs {bench['cierre_mercado']:.0f}%")
        else:
            c_b2.caption(f"• **Inversión:** `${costos.get('Inversion', 0):,.2f}` | Leads: **{int(embudo.get('Resultados (WhatsApp)', 0)):,}**")


def _render_grafica_vendedores(vendedores):
    if not vendedores:
        st.info("No se encontraron registros individuales de vendedores en este bloque mensual.")
        return

    df_v = pd.DataFrame(vendedores)
    c1, c2 = st.columns([1.3, 1.7])

    with c1:
        fig_bar = go.Figure()
        fig_bar.add_trace(go.Bar(
            x=df_v["Vendedor"],
            y=df_v["Asignados / Asistidos"],
            name="Asignados / Asistidos",
            marker_color="#64748B",
            text=df_v["Asignados / Asistidos"],
            textposition="auto"
        ))
        fig_bar.add_trace(go.Bar(
            x=df_v["Vendedor"],
            y=df_v["Vendidos"],
            name="Vendidos",
            marker_color="#10B981",
            text=df_v["Vendidos"],
            textposition="auto"
        ))
        fig_bar.update_layout(
            title="👥 Asignados vs Vendidos por Vendedor",
            barmode="group",
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=400
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    with c2:
        colores_ef = ["#10B981" if e >= 50.0 else "#EF4444" for e in df_v["Efectividad (%)"]]
        fig_ef = go.Figure(go.Bar(
            x=df_v["Efectividad (%)"],
            y=df_v["Vendedor"],
            orientation="h",
            marker_color=colores_ef,
            text=[f"{e:.1f}%" for e in df_v["Efectividad (%)"]],
            textposition="auto"
        ))
        fig_ef.add_vline(
            x=50.0,
            line_dash="dash",
            line_color="#FACC15",
            annotation_text="Meta Mínima 50%",
            annotation_position="top right"
        )
        fig_ef.update_layout(
            title="🎯 % Efectividad de Cierre (Meta: 50%)",
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis_title="Efectividad (%)",
            yaxis={"categoryorder": "total ascending"},
            height=400
        )
        st.plotly_chart(fig_ef, use_container_width=True)

    st.dataframe(df_v, width="stretch", hide_index=True)


def _render_grafica_contenido_efectivo(contenidos, marca_activa):
    if not contenidos:
        st.info(f"No se encontraron anuncios detallados para **{marca_activa}** en la hoja de Gráfica de Contenido para este mes.")
        return

    df_c = pd.DataFrame(contenidos).sort_values(by=["Resultados", "Impresiones"], ascending=False)
    top_df = df_c.head(8)

    g1, g2 = st.columns([1.4, 1.6])
    with g1:
        fig_top = px.bar(
            top_df,
            x="Resultados",
            y="Nombre del Anuncio",
            orientation="h",
            text="Resultados",
            color="Costo / Res.",
            color_continuous_scale="Tealgrn_r",
            title=f"🏆 Contenido Más Efectivo — {marca_activa}"
        )
        fig_top.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            yaxis={"categoryorder": "total ascending"},
            height=390
        )
        st.plotly_chart(fig_top, use_container_width=True)

    with g2:
        st.markdown("**Detalle de Anuncios (Columna B a Creatividad)**")
        st.dataframe(
            df_c[["Nombre del Anuncio", "Conjunto", "Resultados", "Costo / Res.", "Impresiones", "Alcance", "Creatividad"]],
            width="stretch",
            hide_index=True
        )


# =============================================================================
# CONSULTOR IA INTERACTIVO CONECTADO A LOS RESULTADOS DEL MES
# =============================================================================
def _render_consultor_ia_resultados(db, marca_activa, mes_sel, embudo, costos, vendedores, contenidos, score_salud, justif_mercado, hist_marca, es_zae):
    """
    Permite hacer preguntas abiertas o usar botones de diagnóstico rápido sobre los
    resultados reales del mes seleccionado para obtener recomendaciones accionables.
    """
    st.markdown("---")
    st.markdown(f"### 🧠 Consultor IA de Resultados — {marca_activa} ({mes_sel})")
    st.caption("Pregunta libremente o selecciona una consulta rápida. La IA ya tiene cargados todos tus números reales de este mes y la comparativa del mercado.")

    api_key = _obtener_api_key(db)
    if not api_key:
        st.warning("⚠️ El servicio de Inteligencia Artificial no está configurado en el servidor (`GEMINI_API_KEY`).")
        return

    b1, b2, b3, b4 = st.columns(4)
    prompt_seleccionado = None

    if b1.button("📊 Opinión de este mes", width="stretch", key=f"ia_op_{marca_activa}_{mes_sel}"):
        prompt_seleccionado = "Dame tu opinión ejecutiva sobre los resultados de este mes: ¿qué está funcionando muy bien, qué puntos de alerta detectas y cómo nos posicionamos frente al mercado?"

    if b2.button("🚀 Mejorar Meta Ads", width="stretch", key=f"ia_meta_{marca_activa}_{mes_sel}"):
        prompt_seleccionado = "¿Cómo puedo mejorar mis campañas de Meta Ads este mes? Dame acciones concretas en segmentación, presupuesto, creativos y optimización de costos (CPL/CAC)."

    if b3.button("🏆 Escalar / Apagar anuncios", width="stretch", key=f"ia_ads_{marca_activa}_{mes_sel}"):
        prompt_seleccionado = "Analiza el rendimiento de mis anuncios de este mes: dime exactamente qué anuncios debo escalar con más presupuesto, cuáles mantener y cuáles apagar o renovar."

    lbl_b4 = "👥 Analizar vendedores" if es_zae else "🎯 Plan próximo mes"
    if b4.button(lbl_b4, width="stretch", key=f"ia_b4_{marca_activa}_{mes_sel}"):
        if es_zae:
            prompt_seleccionado = "Analiza la efectividad de mis vendedores (meta 50%): quiénes lideran, quiénes requieren capacitación urgente y cómo mejorar la conversión de citas asistidas a ventas."
        else:
            prompt_seleccionado = "Con base en los resultados de este mes y la tendencia histórica, dame un plan de acción práctico de 4 pasos para superar estas metas el próximo mes."

    q_col1, q_col2 = st.columns([4.2, 1])
    pregunta_usuario = q_col1.text_input(
        "Haz una pregunta específica sobre tus resultados:",
        placeholder="Ej. ¿Por qué subió el CPAC este mes? / ¿Cuánto debo invertir para lograr 150 ventas? / ¿Qué opinas del anuncio Ecatepec?",
        key=f"ia_q_input_{marca_activa}_{mes_sel}"
    )
    q_col2.write("")
    q_col2.write("")
    if q_col2.button("✨ Preguntar a IA", type="primary", width="stretch", key=f"ia_q_btn_{marca_activa}_{mes_sel}"):
        if pregunta_usuario.strip():
            prompt_seleccionado = pregunta_usuario.strip()
        else:
            st.warning("Escribe una pregunta o haz clic en alguno de los botones superiores.")

    clave_sesion_resp = f"resp_ia_resultados_{marca_activa}_{mes_sel}"

    if prompt_seleccionado:
        top_ads_txt = "Sin datos de anuncios individuales."
        if contenidos:
            df_c = pd.DataFrame(contenidos).sort_values(by=["Resultados", "Impresiones"], ascending=False)
            lineas_ads = [
                f"- {r['Nombre del Anuncio']} (Conjunto: {r['Conjunto']}): {r['Resultados']} resultados | CPR: ${r['Costo / Res.']:.2f} | Imp: {r['Impresiones']:,}"
                for _, r in df_c.head(10).iterrows()
            ]
            top_ads_txt = "\n".join(lineas_ads)

        vendedores_txt = "No aplica para esta marca."
        if vendedores:
            lineas_v = [
                f"- {v['Vendedor']}: {v['Vendidos']} vendidos de {v['Asignados / Asistidos']} asistidos ({v['Efectividad (%)']}% - {v['Cumple Meta 50%']})"
                for v in vendedores
            ]
            vendedores_txt = "\n".join(lineas_v)

        hist_txt = "Sin historial previo guardado."
        if hist_marca:
            meses_ord = sorted(list(hist_marca.keys()), key=_clave_orden_mes)
            lineas_h = [
                f"- {m}: Leads={int(hist_marca[m].get('Resultados', 0))}, Citas={int(hist_marca[m].get('Citas', 0))}, Ventas={int(hist_marca[m].get('Ventas', 0))}, Inv=${hist_marca[m].get('Inversion', 0):,.2f}, CPL=${hist_marca[m].get('CPL', 0):.2f}, CAC=${hist_marca[m].get('CAC', 0):.2f}"
                for m in meses_ord
            ]
            hist_txt = "\n".join(lineas_h)

        prompt_completo = f"""
        Actúa como Director de Estrategia de Marketing Digital, Tráfico Pago (Meta Ads) y Analítica Comercial en México.
        Estás asesorando sobre la marca: **{marca_activa}** | Periodo analizado: **{mes_sel}**.

        === DATOS REALES DEL PERIODO ===
- Alcance: {int(embudo.get('Alcance', 0)):,}
- Impresiones: {int(embudo.get('Impresiones', 0)):,}
- Resultados / Leads WhatsApp: {int(embudo.get('Resultados (WhatsApp)', 0)):,}
- Citas Asistidas: {int(embudo.get('Citas Asistidas', 0)):,}
- Ventas Concretadas: {int(embudo.get('Ventas Concretadas', 0)):,}
- Inversión Meta Ads: ${costos.get('Inversion', 0):,.2f} MXN
- Costo por Lead (CPL): ${costos.get('CPL', 0):,.2f} MXN
- Costo por Cita Asistida (CPAC): ${costos.get('CPAC', 0):,.2f} MXN
- CAC Publicitario (Por Venta): ${costos.get('CAC', 0):,.2f} MXN
- Puntaje de Salud de Inversión: {score_salud}/100
- Comparativa vs Mercado Mexicano: {justif_mercado}

        === RENDIMIENTO DE ANUNCIOS (TOP CONTENIDOS) ===
        {top_ads_txt}

        === RENDIMIENTO DE VENDEDORES (META 50%) ===
        {vendedores_txt}

        === COMPARATIVA HISTÓRICA ANUAL ===
        {hist_txt}

        === PREGUNTA O SOLICITUD DEL USUARIO ===
        "{prompt_seleccionado}"

        Instrucciones de respuesta:
- Responde en español, con tono directo, estratégico, claro y accionable (sin relleno innecesario).
- Cita siempre los números reales de la marca para respaldar cada diagnóstico.
- Estructura la respuesta con viñetas claras y recomendaciones prácticas inmediatas.
        """

        try:
            with st.spinner("Analizando métricas, costos y creativos con Inteligencia Artificial..."):
                client = genai.Client(api_key=api_key)
                resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt_completo)
                st.session_state[clave_sesion_resp] = {
                    "pregunta": prompt_seleccionado,
                    "respuesta": resp.text
                }
        except Exception as e:
            st.error(f"Error al consultar la IA: {e}")

    if clave_sesion_resp in st.session_state:
        data_ia = st.session_state[clave_sesion_resp]
        with st.container(border=True):
            st.caption(f"💬 **Consulta:** *{data_ia['pregunta']}*")
            st.markdown(data_ia["respuesta"])


# =============================================================================
# GENERADOR DE KPI DASHBOARD EJECUTIVO DE UNA SOLA HOJA (DESCARGABLE)
# =============================================================================
def _generar_html_kpi_dashboard(marca_activa, mes_etiqueta, embudo, costos, score, estado_salud, justif_mercado, vendedores, contenidos, es_zae):
    """Genera un reporte ejecutivo de una sola página limpio y corporativo con justificación de mercado."""
    alcance = int(embudo.get("Alcance", 0))
    leads = int(embudo.get("Resultados (WhatsApp)", 0))
    citas = int(embudo.get("Citas Asistidas", 0))
    ventas = int(embudo.get("Ventas Concretadas", 0))
    inversion = float(costos.get("Inversion", 0.0))
    cpl = float(costos.get("CPL", 0.0))
    cpac = float(costos.get("CPAC", 0.0))
    cac = float(costos.get("CAC", 0.0))

    ef_cierre = (ventas / citas * 100) if citas > 0 else 0.0

    top_ads_html = ""
    if contenidos:
        df_top = sorted(contenidos, key=lambda x: x.get("Resultados", 0), reverse=True)[:5]
        max_res = max((a.get("Resultados", 0) for a in df_top), default=1) or 1
        for ad in df_top:
            res_val = int(ad.get("Resultados", 0))
            cpr_val = float(ad.get("Costo / Res.", 0))
            pct_bar = int((res_val / max_res) * 100)
            top_ads_html += f"""
            <tr>
                <td style="font-weight:600; color:#1E293B;">{ad.get('Nombre del Anuncio', '')[:32]}</td>
                <td style="text-align:right; font-weight:700;">{res_val:,}</td>
                <td style="width:110px;">
                    <div style="background:#E2E8F0; border-radius:99px; height:8px; width:100%;">
                        <div style="background:#0D9488; height:8px; border-radius:99px; width:{pct_bar}%;"></div>
                    </div>
                </td>
                <td style="text-align:right; color:#475569;">${cpr_val:,.2f}</td>
            </tr>
            """
    else:
        top_ads_html = "<tr><td colspan='4' style='color:#64748B; text-align:center;'>Sin detalle de anuncios en este periodo</td></tr>"

    if es_zae and vendedores:
        bloque_der_titulo = "EFECTIVIDAD DE VENDEDORES (META 50%)"
        filas_v = ""
        for v in vendedores[:5]:
            ef_v = v.get("Efectividad (%)", 0)
            color_v = "#10B981" if ef_v >= 50 else "#EF4444"
            filas_v += f"""
            <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 0; border-bottom:1px solid #F1F5F9; font-size:12px;">
                <span style="font-weight:600;">{v['Vendedor']}</span>
                <span style="color:#64748B;">{v['Vendidos']}/{v['Asignados / Asistidos']} cierres</span>
                <span style="font-weight:800; color:{color_v};">{ef_v:.1f}%</span>
            </div>
            """
        bloque_der_html = filas_v
    else:
        bloque_der_titulo = "COSTOS UNITARIOS Y RENTABILIDAD"
        bloque_der_html = f"""
        <div style="padding:10px 0; border-bottom:1px solid #F1F5F9; display:flex; justify-content:space-between;">
            <span style="color:#475569;">Costo por Lead (CPL)</span>
            <strong style="color:#0F172A; font-size:15px;">${cpl:,.2f}</strong>
        </div>
        <div style="padding:10px 0; border-bottom:1px solid #F1F5F9; display:flex; justify-content:space-between;">
            <span style="color:#475569;">Costo por Cita (CPAC)</span>
            <strong style="color:#0F172A; font-size:15px;">${cpac:,.2f}</strong>
        </div>
        <div style="padding:10px 0; display:flex; justify-content:space-between;">
            <span style="color:#475569;">CAC Publicitario</span>
            <strong style="color:#0D9488; font-size:16px;">${cac:,.2f}</strong>
        </div>
        """

    w_alc = 100
    w_lea = max(18, int((leads / alcance) * 100)) if alcance > 0 else 65
    w_cit = max(14, int((citas / leads) * 80)) if leads > 0 else 40
    w_ven = max(10, int((ventas / leads) * 70)) if leads > 0 else 25

    mejor_anuncio = sorted(contenidos, key=lambda x: x.get("Resultados", 0), reverse=True)[0]["Nombre del Anuncio"] if contenidos else "N/A"
    vendedores_meta = sum(1 for v in vendedores if v.get("Efectividad (%)", 0) >= 50)
    pct_vendedores_ok = int((vendedores_meta / len(vendedores)) * 100) if vendedores else int(min(ef_cierre * 2, 100))

    html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
    <meta charset="UTF-8">
    <title>KPI Dashboard - {marca_activa} ({mes_etiqueta})</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            background-color: #E2E8F0;
            font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 20px;
            color: #1E293B;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }}
        .page {{
            max-width: 1080px;
            margin: 0 auto;
            background: #FFFFFF;
            border-radius: 16px;
            padding: 28px 34px;
            box-shadow: 0 10px 30px rgba(15,23,42,0.12);
        }}
        .header-top {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 22px;
            border-bottom: 2px solid #F1F5F9;
            padding-bottom: 16px;
        }}
        .title-block h1 {{
            margin: 0;
            font-size: 32px;
            font-weight: 900;
            color: #0F766E;
            letter-spacing: 0.5px;
            line-height: 1.05;
        }}
        .title-block .sub {{
            font-size: 13px;
            font-weight: 700;
            color: #334155;
            margin-top: 4px;
        }}
        .steps-row {{
            display: flex;
            gap: 12px;
            align-items: center;
        }}
        .step-badge {{
            text-align: center;
            width: 78px;
        }}
        .step-circle {{
            width: 48px;
            height: 48px;
            border-radius: 50%;
            margin: 0 auto 5px auto;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #FFFFFF;
            font-weight: 800;
            font-size: 15px;
            border: 3px solid #F8FAFC;
            box-shadow: 0 3px 8px rgba(0,0,0,0.12);
        }}
        .step-pill {{
            font-size: 9px;
            font-weight: 700;
            color: #FFFFFF;
            padding: 2px 6px;
            border-radius: 4px;
            text-transform: uppercase;
        }}
        .kpi-grid-6 {{
            display: grid;
            grid-template-columns: repeat(6, 1fr);
            gap: 12px;
            margin-bottom: 20px;
        }}
        .kpi-card {{
            border: 1px solid #E2E8F0;
            border-radius: 12px;
            padding: 12px;
            background: #FFFFFF;
            box-shadow: 0 2px 6px rgba(15,23,42,0.04);
        }}
        .kpi-head {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 8px;
        }}
        .kpi-ico {{
            width: 28px;
            height: 28px;
            border-radius: 50%;
            color: #FFF;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 13px;
            font-weight: bold;
        }}
        .kpi-lbl {{
            font-size: 9.5px;
            font-weight: 700;
            color: #64748B;
            text-transform: uppercase;
        }}
        .kpi-num {{
            font-size: 19px;
            font-weight: 800;
            color: #0F172A;
            margin-bottom: 8px;
        }}
        .spark-bars {{
            display: flex;
            align-items: flex-end;
            gap: 4px;
            height: 24px;
        }}
        .spark-bars span {{
            flex: 1;
            border-radius: 2px 2px 0 0;
        }}
        .mid-grid {{
            display: grid;
            grid-template-columns: 1fr 1.25fr 1fr;
            gap: 16px;
            margin-bottom: 18px;
        }}
        .panel {{
            border: 1px solid #E2E8F0;
            border-radius: 12px;
            padding: 14px 16px;
            background: #FFFFFF;
        }}
        .panel-title {{
            font-size: 11px;
            font-weight: 800;
            color: #0F172A;
            text-transform: uppercase;
            border-left: 4px solid #0F766E;
            padding-left: 8px;
            margin-bottom: 12px;
        }}
        .funnel-step {{
            margin-bottom: 8px;
        }}
        .funnel-meta {{
            display: flex;
            justify-content: space-between;
            font-size: 11px;
            font-weight: 600;
            margin-bottom: 3px;
        }}
        .funnel-bar {{
            height: 16px;
            border-radius: 6px;
            margin: 0 auto;
        }}
        .table-clean {{
            width: 100%;
            border-collapse: collapse;
            font-size: 11.5px;
        }}
        .table-clean th {{
            text-align: left;
            color: #64748B;
            font-size: 10px;
            padding-bottom: 6px;
            border-bottom: 1px solid #E2E8F0;
        }}
        .table-clean td {{
            padding: 7px 4px;
            border-bottom: 1px solid #F1F5F9;
        }}
        .bot-grid {{
            display: grid;
            grid-template-columns: 1.45fr 0.85fr;
            gap: 16px;
        }}
        .insights-row {{
            display: grid;
            grid-template-columns: 1.4fr 1fr 1fr;
            gap: 10px;
        }}
        .insight-item {{
            background: #F8FAFC;
            border-radius: 10px;
            padding: 10px;
            font-size: 10.5px;
            line-height: 1.4;
        }}
        .rings-row {{
            display: flex;
            justify-content: space-around;
            align-items: center;
            padding-top: 6px;
        }}
        .ring-box {{
            text-align: center;
        }}
        .ring {{
            width: 66px;
            height: 66px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 6px auto;
            font-weight: 800;
            font-size: 15px;
        }}
        @media print {{
            body {{ background: #FFF; padding: 0; }}
            .page {{ box-shadow: none; }}
        }}
    </style>
    </head>
    <body>
    <div class="page">
        <div class="header-top">
            <div class="title-block">
                <h1>KPI DASHBOARD</h1>
                <div class="sub">{marca_activa.upper()} &nbsp;|&nbsp; PERIODO: {mes_etiqueta}</div>
            </div>
            <div class="steps-row">
                <div class="step-badge">
                    <div class="step-circle" style="background:#F59E0B;">👁️</div>
                    <span class="step-pill" style="background:#64748B;">Alcance</span>
                </div>
                <div class="step-badge">
                    <div class="step-circle" style="background:#0D9488;">💬</div>
                    <span class="step-pill" style="background:#0D9488;">Leads WA</span>
                </div>
                <div class="step-badge">
                    <div class="step-circle" style="background:#EF4444;">📅</div>
                    <span class="step-pill" style="background:#EF4444;">Citas</span>
                </div>
                <div class="step-badge">
                    <div class="step-circle" style="background:#F59E0B;">🏆</div>
                    <span class="step-pill" style="background:#F59E0B;">Ventas</span>
                </div>
                <div class="step-badge">
                    <div class="step-circle" style="background:#3B82F6;">💰</div>
                    <span class="step-pill" style="background:#3B82F6;">Costos</span>
                </div>
                <div class="step-badge">
                    <div class="step-circle" style="background:#10B981;">🩺</div>
                    <span class="step-pill" style="background:#10B981;">Salud</span>
                </div>
            </div>
        </div>

        <div class="kpi-grid-6">
            <div class="kpi-card">
                <div class="kpi-head"><div class="kpi-ico" style="background:#0F766E;">$</div><div class="kpi-lbl">Inversión</div></div>
                <div class="kpi-num">${inversion:,.0f}</div>
                <div class="spark-bars">
                    <span style="height:45%;background:#0F766E;"></span><span style="height:60%;background:#0F766E;"></span>
                    <span style="height:75%;background:#0F766E;"></span><span style="height:65%;background:#0F766E;"></span>
                    <span style="height:90%;background:#0F766E;"></span><span style="height:100%;background:#0F766E;"></span>
                </div>
            </div>
            <div class="kpi-card">
                <div class="kpi-head"><div class="kpi-ico" style="background:#F59E0B;">💬</div><div class="kpi-lbl">Leads WA</div></div>
                <div class="kpi-num">{leads:,}</div>
                <div class="spark-bars">
                    <span style="height:50%;background:#F59E0B;"></span><span style="height:70%;background:#F59E0B;"></span>
                    <span style="height:60%;background:#F59E0B;"></span><span style="height:85%;background:#F59E0B;"></span>
                    <span style="height:95%;background:#F59E0B;"></span><span style="height:100%;background:#F59E0B;"></span>
                </div>
            </div>
            <div class="kpi-card">
                <div class="kpi-head"><div class="kpi-ico" style="background:#4F46E5;">📅</div><div class="kpi-lbl">Citas Asist.</div></div>
                <div class="kpi-num">{citas:,}</div>
                <div class="spark-bars">
                    <span style="height:40%;background:#4F46E5;"></span><span style="height:65%;background:#4F46E5;"></span>
                    <span style="height:80%;background:#4F46E5;"></span><span style="height:70%;background:#4F46E5;"></span>
                    <span style="height:85%;background:#4F46E5;"></span><span style="height:95%;background:#4F46E5;"></span>
                </div>
            </div>
            <div class="kpi-card">
                <div class="kpi-head"><div class="kpi-ico" style="background:#0D9488;">🏆</div><div class="kpi-lbl">Ventas</div></div>
                <div class="kpi-num">{ventas:,}</div>
                <div class="spark-bars">
                    <span style="height:35%;background:#0D9488;"></span><span style="height:55%;background:#0D9488;"></span>
                    <span style="height:70%;background:#0D9488;"></span><span style="height:80%;background:#0D9488;"></span>
                    <span style="height:90%;background:#0D9488;"></span><span style="height:100%;background:#0D9488;"></span>
                </div>
            </div>
            <div class="kpi-card">
                <div class="kpi-head"><div class="kpi-ico" style="background:#EF4444;">⚡</div><div class="kpi-lbl">CPL / CAC</div></div>
                <div class="kpi-num">${(cac if cac > 0 else cpl):,.2f}</div>
                <div class="spark-bars">
                    <span style="height:90%;background:#EF4444;"></span><span style="height:75%;background:#EF4444;"></span>
                    <span style="height:65%;background:#EF4444;"></span><span style="height:60%;background:#EF4444;"></span>
                    <span style="height:50%;background:#EF4444;"></span><span style="height:45%;background:#EF4444;"></span>
                </div>
            </div>
            <div class="kpi-card">
                <div class="kpi-head"><div class="kpi-ico" style="background:#6366F1;">🩺</div><div class="kpi-lbl">Salud Inv.</div></div>
                <div class="kpi-num">{score}/100</div>
                <div class="spark-bars">
                    <span style="height:50%;background:#6366F1;"></span><span style="height:60%;background:#6366F1;"></span>
                    <span style="height:75%;background:#6366F1;"></span><span style="height:80%;background:#6366F1;"></span>
                    <span style="height:90%;background:#6366F1;"></span><span style="height:{score}%;background:#6366F1;"></span>
                </div>
            </div>
        </div>

        <div class="mid-grid">
            <div class="panel">
                <div class="panel-title">EMBUDO DE CONVERSIÓN</div>
                <div class="funnel-step">
                    <div class="funnel-meta"><span>Alcance</span><span>{alcance:,}</span></div>
                    <div class="funnel-bar" style="width:{w_alc}%; background:#1E3A8A;"></div>
                </div>
                <div class="funnel-step">
                    <div class="funnel-meta"><span>Resultados (WhatsApp)</span><span>{leads:,}</span></div>
                    <div class="funnel-bar" style="width:{w_lea}%; background:#2563EB;"></div>
                </div>
                <div class="funnel-step">
                    <div class="funnel-meta"><span>Citas Asistidas</span><span>{citas:,}</span></div>
                    <div class="funnel-bar" style="width:{w_cit}%; background:#0D9488;"></div>
                </div>
                <div class="funnel-step">
                    <div class="funnel-meta"><span>Ventas Concretadas</span><span>{ventas:,}</span></div>
                    <div class="funnel-bar" style="width:{w_ven}%; background:#10B981;"></div>
                </div>
            </div>

            <div class="panel">
                <div class="panel-title">CONTENIDO MÁS EFECTIVO (TOP ANUNCIOS)</div>
                <table class="table-clean">
                    <thead>
                        <tr><th>Anuncio</th><th style="text-align:right;">Res.</th><th>Impacto</th><th style="text-align:right;">CPR</th></tr>
                    </thead>
                    <tbody>{top_ads_html}</tbody>
                </table>
            </div>

            <div class="panel">
                <div class="panel-title">{bloque_der_titulo}</div>
                {bloque_der_html}
            </div>
        </div>

        <div class="bot-grid">
            <div class="panel">
                <div class="panel-title">KEY INSIGHTS &amp; JUSTIFICACIÓN DE MERCADO</div>
                <div class="insights-row">
                    <div class="insight-item">
                        <strong style="color:#0F766E;">🩺 {estado_salud}</strong><br>
                        {justif_mercado}
                    </div>
                    <div class="insight-item">
                        <strong style="color:#D97706;">🏆 Anuncio Líder</strong><br>
                        El creativo con mayor tracción en el periodo fue <strong>{mejor_anuncio[:35]}</strong>.
                    </div>
                    <div class="insight-item">
                        <strong style="color:#DC2626;">🎯 Enfoque Comercial</strong><br>
                        CPL: <strong>${cpl:,.2f}</strong> &bull; CPAC: <strong>${cpac:,.2f}</strong> &bull; CAC: <strong>${cac:,.2f}</strong>.
                    </div>
                </div>
            </div>

            <div class="panel">
                <div class="panel-title">GOALS PROGRESS</div>
                <div class="rings-row">
                    <div class="ring-box">
                        <div class="ring" style="border:6px solid #0F766E; color:#0F766E;">{score}%</div>
                        <small style="font-weight:700; color:#475569;">Salud Inversión</small>
                    </div>
                    <div class="ring-box">
                        <div class="ring" style="border:6px solid #F59E0B; color:#D97706;">{ef_cierre:.0f}%</div>
                        <small style="font-weight:700; color:#475569;">Cierre Cita→Venta</small>
                    </div>
                    <div class="ring-box">
                        <div class="ring" style="border:6px solid #4F46E5; color:#4F46E5;">{pct_vendedores_ok}%</div>
                        <small style="font-weight:700; color:#475569;">Meta Vendedores</small>
                    </div>
                </div>
            </div>
        </div>
    </div>
    </body>
    </html>
    """
    return html


# =============================================================================
# META ADS DIRECTO (OPCIÓN 2)
# =============================================================================
def _extraer_resultados_meta_fila(item_api, marca_nombre):
    camp = str(item_api.get("campaign_name", "")).lower()
    adset = str(item_api.get("adset_name", "")).lower()
    ad = str(item_api.get("ad_name", "")).lower()
    txt_todo = f"{camp} {adset} {ad}"
    m_low = marca_nombre.lower()

    es_wa = (
        "whatsapp" in txt_todo
        or ("zona auto" in m_low and "interaccion" in txt_todo)
        or ("tvs" in m_low and "interaccion" in txt_todo)
    )

    actions = item_api.get("actions", []) or []
    mapa_acciones = {act.get("action_type", ""): float(act.get("value", 0) or 0) for act in actions}

    if es_wa:
        for clave_wa in [
            "onsite_conversion.messaging_conversation_started_7d",
            "onsite_conversion.total_messaging_connection",
            "onsite_conversion.messaging_first_reply",
            "lead"
        ]:
            if mapa_acciones.get(clave_wa, 0) > 0:
                return int(mapa_acciones[clave_wa]), True

    for clave_otro in ["lead", "onsite_conversion.lead_grouped", "post_engagement", "link_click", "like"]:
        if mapa_acciones.get(clave_otro, 0) > 0:
            return int(mapa_acciones[clave_otro]), es_wa

    return 0, es_wa


def _descargar_insights_meta_directo(ad_account_id, access_token, since_str, until_str, marca_nombre):
    if not ad_account_id or not access_token:
        raise ValueError("Falta el ID de Cuenta Publicitaria (Ad Account ID) o el Token de Acceso de Meta.")

    acc_clean = ad_account_id.strip()
    if not acc_clean.startswith("act_"):
        acc_clean = f"act_{acc_clean}"

    url = f"https://graph.facebook.com/v21.0/{acc_clean}/insights"
    params = {
        "access_token": access_token.strip(),
        "level": "ad",
        "time_range": json.dumps({"since": since_str, "until": until_str}),
        "time_increment": 1,
        "fields": "date_start,campaign_name,adset_name,ad_name,spend,impressions,reach,actions",
        "limit": 500
    }

    registros = []
    next_url = url
    next_params = params

    while next_url:
        resp = requests.get(next_url, params=next_params, timeout=30)
        data = resp.json()
        if "error" in data:
            raise RuntimeError(data["error"].get("message", "Error desconocido en Meta Marketing API"))

        for row in data.get("data", []):
            gasto = float(row.get("spend", 0) or 0)
            imp = int(row.get("impressions", 0) or 0)
            alcance = int(row.get("reach", 0) or 0)
            res, es_wa = _extraer_resultados_meta_fila(row, marca_nombre)
            cpr = round(gasto / res, 2) if res > 0 else 0.0

            registros.append({
                "FECHA": row.get("date_start", since_str),
                "MES": str(row.get("date_start", since_str))[:7],
                "CAMPANA": row.get("campaign_name", ""),
                "CONJUNTO": row.get("adset_name", ""),
                "ANUNCIO": row.get("ad_name", ""),
                "GASTO": round(gasto, 2),
                "IMPRESIONES": imp,
                "ALCANCE": alcance,
                "RESULTADOS": res,
                "CPR": cpr,
                "ES_WA": es_wa
            })

        paging = data.get("paging", {})
        next_url = paging.get("next")
        next_params = None

    return registros


# =============================================================================
# RENDER PRINCIPAL DEL MÓDULO 5 (AUTOMÁTICO Y SIN TALACHA)
# =============================================================================
def render():
    db = st.session_state.db
    marca_activa = db.get("marca_activa", "General")
    es_zae = _es_zona_autoestrena(marca_activa)

    st.subheader(f"📊 Resultados y Analítica Automática — {marca_activa}")

    if not PLOTLY_INSTALLED:
        st.error("⚠️ Falta la librería gráfica 'plotly'. Abre tu terminal en VS Code y ejecuta: `pip install plotly`")
        return

    cfg = db.setdefault("config_resultados", {})
    cfg.setdefault("url_archivo_maestro", cfg.get("url_hoja_libre", ""))
    cfg.setdefault("por_marca", {})
    cfg.setdefault("historial_anual", {})
    cfg.setdefault("meta_ads_creds", {})
    cfg.setdefault("meta_ads_data", {})

    if marca_activa not in cfg["por_marca"]:
        cfg["por_marca"][marca_activa] = {
            "hoja_principal": "SEGUNDA ETAPA ZONA AUTOESTRENA" if es_zae else "GRAFICA CONTENIDO",
            "hoja_secundaria": "GRAFICA CONTENIDO"
        }

    cfg_marca = cfg["por_marca"][marca_activa]
    if "hoja_destino" in cfg_marca and "hoja_principal" not in cfg_marca:
        cfg_marca["hoja_principal"] = cfg_marca["hoja_destino"]
    cfg_marca.setdefault("hoja_principal", "SEGUNDA ETAPA ZONA AUTOESTRENA" if es_zae else "GRAFICA CONTENIDO")
    cfg_marca.setdefault("hoja_secundaria", "GRAFICA CONTENIDO")

    creds_meta = cfg["meta_ads_creds"].setdefault(marca_activa, {"ad_account_id": "", "meta_token": ""})

    modo = st.radio(
        "Selecciona el modo de trabajo:",
        [
            "📉 Opción 1: Reporte Automático desde Google Sheets (Embudo, Costos, Vendedores y Anual)",
            "🚀 Opción 2: Descarga Directa Meta Ads API en la App (Sin Google Sheets)"
        ],
        horizontal=True
    )

    st.markdown("---")

    url_guardada = cfg.get("url_archivo_maestro", "")
    sheet_id = _extraer_sheet_id(url_guardada)
    mapa_pestanas = _obtener_mapa_pestanas(sheet_id) if sheet_id else {}
    pestanas_detectadas = list(mapa_pestanas.keys())

    with st.expander(
        f"🔗 Conexión de Archivo y Hojas ({cfg_marca['hoja_principal']} + {cfg_marca['hoja_secundaria']})",
        expanded=not bool(sheet_id)
    ):
        st.caption("Pega el enlace de tu Google Sheet **una sola vez**. Las hojas de cada marca ya vienen preconfiguradas automáticamente.")

        c_u1, c_u2, c_u3 = st.columns([4, 1.2, 1])
        url_maestra_in = c_u1.text_input(
            "Enlace General del Archivo (Google Sheets):",
            value=url_guardada,
            placeholder="https://docs.google.com/spreadsheets/d/...",
            key=f"url_maestro_m5_{marca_activa}"
        )
        c_u2.write("")
        c_u2.write("")
        if c_u2.button("💾 Guardar Enlace", type="primary", width="stretch", key=f"save_url_m5_{marca_activa}"):
            cfg["url_archivo_maestro"] = url_maestra_in.strip()
            guardar_datos(db)
            st.cache_data.clear()
            st.success("Enlace guardado.")
            st.rerun()

        c_u3.write("")
        c_u3.write("")
        if c_u3.button("🔄 Actualizar", width="stretch", key=f"ref_m5_{marca_activa}"):
            st.cache_data.clear()
            st.rerun()

        opciones_hojas = []
        for p in pestanas_detectadas + HOJAS_CONOCIDAS_DEFAULT:
            if p not in opciones_hojas:
                opciones_hojas.append(p)
        opciones_hojas.append("✍️ Escribir manualmente...")

        h_col1, h_col2, h_col3 = st.columns([2, 2, 1.2])
        h1_saved = cfg_marca.get("hoja_principal", opciones_hojas[0])
        idx_h1 = opciones_hojas.index(h1_saved) if h1_saved in opciones_hojas else len(opciones_hojas) - 1
        sel_h1 = h_col1.selectbox(f"Hoja Principal ({marca_activa}):", opciones_hojas, index=idx_h1, key=f"sel_h1_{marca_activa}")
        final_h1 = h_col1.text_input("Nombre Hoja 1:", value=h1_saved if h1_saved not in opciones_hojas else "", key=f"txt_h1_{marca_activa}") if sel_h1.startswith("✍️") else sel_h1

        h2_saved = cfg_marca.get("hoja_secundaria", "GRAFICA CONTENIDO")
        idx_h2 = opciones_hojas.index(h2_saved) if h2_saved in opciones_hojas else len(opciones_hojas) - 1
        sel_h2 = h_col2.selectbox("Hoja Secundaria (Contenido):", opciones_hojas, index=idx_h2, key=f"sel_h2_{marca_activa}")
        final_h2 = h_col2.text_input("Nombre Hoja 2:", value=h2_saved if h2_saved not in opciones_hojas else "", key=f"txt_h2_{marca_activa}") if sel_h2.startswith("✍️") else sel_h2

        h_col3.write("")
        h_col3.write("")
        if h_col3.button("💾 Guardar Hojas", width="stretch", key=f"save_hojas_m5_{marca_activa}"):
            cfg_marca["hoja_principal"] = final_h1.strip()
            cfg_marca["hoja_secundaria"] = final_h2.strip()
            guardar_datos(db)
            st.success(f"Hojas guardadas para {marca_activa}.")
            st.rerun()

    sheet_id = _extraer_sheet_id(cfg.get("url_archivo_maestro", ""))

    # =========================================================================
    # OPCIÓN 1: DASHBOARD 100% AUTOMÁTICO POR MARCA + HISTORIAL ANUAL + IA
    # =========================================================================
    if modo.startswith("📉"):
        if not sheet_id:
            st.info("Pega arriba el enlace de tu archivo de Google Sheets y presiona **Guardar Enlace** para generar todas las gráficas automáticamente.")
            return

        hoja_1 = cfg_marca.get("hoja_principal", "").strip()
        hoja_2 = cfg_marca.get("hoja_secundaria", "").strip()

        # ---------------------------------------------------------------------
        # RAMA A: EXCLUSIVO ZONA AUTOESTRENA
        # ---------------------------------------------------------------------
        if es_zae:
            try:
                df_h1 = _descargar_hoja_cruda(sheet_id, hoja_1)
                datos_meses_zae = _extraer_datos_zona_autoestrena(df_h1)
            except Exception as e:
                st.error(f"Error al leer la hoja '{hoja_1}': {e}")
                return

            if not datos_meses_zae:
                st.warning(f"No se detectaron bloques mensuales a partir de la columna N en '{hoja_1}'.")
                return

            datos_contenido_zae = {}
            if hoja_2:
                try:
                    df_h2 = _descargar_hoja_cruda(sheet_id, hoja_2)
                    datos_contenido_zae = _extraer_datos_grafica_contenido(df_h2, marca_activa)
                except Exception:
                    pass

            meses_disponibles = sorted(list(datos_meses_zae.keys()), key=_clave_orden_mes)

            top_c1, top_c2, top_c3 = st.columns([2, 1.5, 1.5])
            mes_sel = top_c1.selectbox(
                "Mes del Reporte:",
                meses_disponibles,
                index=len(meses_disponibles) - 1,
                key=f"mes_zae_{marca_activa}"
            )

            bloque_actual = datos_meses_zae[mes_sel]
            embudo = bloque_actual["embudo"]
            vendedores = bloque_actual["vendedores"]
            costos = bloque_actual["costos"]

            contenidos_mes = datos_contenido_zae.get(mes_sel, {}).get("contenidos", [])
            if not contenidos_mes and datos_contenido_zae:
                mes_palabra = mes_sel.split()[0] if mes_sel else ""
                for k_m, v_m in datos_contenido_zae.items():
                    if mes_palabra and mes_palabra in k_m and v_m.get("contenidos"):
                        contenidos_mes = v_m["contenidos"]
                        break
            if not contenidos_mes and datos_contenido_zae:
                ultimo_k = sorted(list(datos_contenido_zae.keys()), key=_clave_orden_mes)[-1]
                contenidos_mes = datos_contenido_zae[ultimo_k].get("contenidos", [])

            score_salud, estado_salud, justif_mercado, bench = _calcular_salud_inversion(embudo, costos, es_zae=True, marca_nombre=marca_activa)

            top_c2.write("")
            top_c2.write("")
            if top_c2.button("💾 Guardar en Comparativa Anual", type="primary", width="stretch", key=f"save_hist_zae_{mes_sel}"):
                hist_marca = cfg["historial_anual"].setdefault(marca_activa, {})
                for m_lbl, m_data in datos_meses_zae.items():
                    sc, _, _, _ = _calcular_salud_inversion(m_data["embudo"], m_data["costos"], es_zae=True, marca_nombre=marca_activa)
                    hist_marca[m_lbl] = {
                        "mes_reporte": m_lbl,
                        "Alcance": m_data["embudo"].get("Alcance", 0),
                        "Resultados": m_data["embudo"].get("Resultados (WhatsApp)", 0),
                        "Citas": m_data["embudo"].get("Citas Asistidas", 0),
                        "Ventas": m_data["embudo"].get("Ventas Concretadas", 0),
                        "Inversion": m_data["costos"].get("Inversion", 0),
                        "CPL": m_data["costos"].get("CPL", 0),
                        "CPAC": m_data["costos"].get("CPAC", 0),
                        "CAC": m_data["costos"].get("CAC", 0),
                        "Salud": sc
                    }
                guardar_datos(db)
                st.success(f"Guardados {len(datos_meses_zae)} mes(es) en el historial anual por título de mes.")
                st.rerun()

            html_dash = _generar_html_kpi_dashboard(
                marca_activa, mes_sel, embudo, costos, score_salud, estado_salud, justif_mercado, vendedores, contenidos_mes, es_zae=True
            )
            top_c3.write("")
            top_c3.write("")
            top_c3.download_button(
                label="📥 Descargar Dashboard (1 Hoja)",
                data=html_dash.encode("utf-8"),
                file_name=f"KPI_Dashboard_{marca_activa.replace(' ', '_')}_{mes_sel.replace(' ', '_')}.html",
                mime="text/html",
                width="stretch"
            )

            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Alcance", f"{int(embudo['Alcance']):,}")
            k2.metric("Resultados (WA)", f"{int(embudo['Resultados (WhatsApp)']):,}")
            k3.metric("Citas Asistidas", f"{int(embudo['Citas Asistidas']):,}")
            k4.metric("Ventas Concretadas", f"{int(embudo['Ventas Concretadas']):,}")
            k5.metric("Inversión Meta Ads", f"${costos['Inversion']:,.2f}")

            g_r1_c1, g_r1_c2 = st.columns([1.25, 1.05])
            with g_r1_c1:
                _render_grafica_embudo(embudo, f"🔻 Embudo de Conversión — {mes_sel}")
            with g_r1_c2:
                _render_medidor_salud(score_salud, estado_salud, justif_mercado, embudo, costos, bench, es_zae=True)

            st.markdown("---")
            _render_grafica_costos_barras(costos, f"💸 Costos Publicitarios y Rentabilidad — {mes_sel}")

            st.markdown("---")
            st.markdown(f"#### 🏆 Efectividad de Vendedores (Asignados vs Vendidos • Meta 50%) — {mes_sel}")
            _render_grafica_vendedores(vendedores)

            st.markdown("---")
            st.markdown(f"#### 🔥 Contenido Más Efectivo (Cruzado desde `{hoja_2}`)")
            _render_grafica_contenido_efectivo(contenidos_mes, marca_activa)

            hist_actual_marca = cfg.get("historial_anual", {}).get(marca_activa, {})
            _render_consultor_ia_resultados(
                db, marca_activa, mes_sel, embudo, costos, vendedores, contenidos_mes, score_salud, justif_mercado, hist_actual_marca, es_zae=True
            )

        # ---------------------------------------------------------------------
        # RAMA B: DEMÁS MARCAS (TVS, BANDA BIKER, LEAD ZONE PRO, ETC.)
        # ---------------------------------------------------------------------
        else:
            try:
                df_h1 = _descargar_hoja_cruda(sheet_id, hoja_1)
                datos_meses_marca = _extraer_datos_grafica_contenido(df_h1, marca_activa)
            except Exception as e:
                st.error(f"Error al leer la hoja '{hoja_1}': {e}")
                return

            if not datos_meses_marca:
                st.warning(f"No se encontraron bloques para **{marca_activa}** en '{hoja_1}'. Verifica que el título en la hoja diga `REPORTE {marca_activa.upper()} - MES`.")
                return

            meses_disponibles = sorted(list(datos_meses_marca.keys()), key=_clave_orden_mes)

            top_c1, top_c2, top_c3 = st.columns([2, 1.5, 1.5])
            mes_sel = top_c1.selectbox(
                "Mes del Reporte:",
                meses_disponibles,
                index=len(meses_disponibles) - 1,
                key=f"mes_otra_{marca_activa}"
            )

            bloque_actual = datos_meses_marca[mes_sel]
            embudo = bloque_actual["embudo"]
            costos = bloque_actual["costos"]
            contenidos_mes = bloque_actual["contenidos"]

            score_salud, estado_salud, justif_mercado, bench = _calcular_salud_inversion(embudo, costos, es_zae=False, marca_nombre=marca_activa)

            top_c2.write("")
            top_c2.write("")
            if top_c2.button("💾 Guardar en Comparativa Anual", type="primary", width="stretch", key=f"save_hist_otra_{marca_activa}_{mes_sel}"):
                hist_marca = cfg["historial_anual"].setdefault(marca_activa, {})
                for m_lbl, m_data in datos_meses_marca.items():
                    sc, _, _, _ = _calcular_salud_inversion(m_data["embudo"], m_data["costos"], es_zae=False, marca_nombre=marca_activa)
                    hist_marca[m_lbl] = {
                        "mes_reporte": m_lbl,
                        "Alcance": m_data["embudo"].get("Alcance", 0),
                        "Resultados": m_data["embudo"].get("Resultados (WhatsApp)", 0),
                        "Citas": m_data["embudo"].get("Citas Asistidas", 0),
                        "Ventas": m_data["embudo"].get("Ventas Concretadas", 0),
                        "Inversion": m_data["costos"].get("Inversion", 0),
                        "CPL": m_data["costos"].get("CPL", 0),
                        "CPAC": m_data["costos"].get("CPAC", 0),
                        "CAC": m_data["costos"].get("CAC", 0),
                        "Salud": sc
                    }
                guardar_datos(db)
                st.success(f"Guardados {len(datos_meses_marca)} mes(es) en el historial anual de {marca_activa}.")
                st.rerun()

            html_dash = _generar_html_kpi_dashboard(
                marca_activa, mes_sel, embudo, costos, score_salud, estado_salud, justif_mercado, [], contenidos_mes, es_zae=False
            )
            top_c3.write("")
            top_c3.write("")
            top_c3.download_button(
                label="📥 Descargar Dashboard (1 Hoja)",
                data=html_dash.encode("utf-8"),
                file_name=f"KPI_Dashboard_{marca_activa.replace(' ', '_')}_{mes_sel.replace(' ', '_')}.html",
                mime="text/html",
                width="stretch"
            )

            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Alcance", f"{int(embudo['Alcance']):,}")
            k2.metric("Resultados (WA)", f"{int(embudo['Resultados (WhatsApp)']):,}")
            k3.metric("Citas Asistidas", f"{int(embudo['Citas Asistidas']):,}")
            k4.metric("Ventas Concretadas", f"{int(embudo['Ventas Concretadas']):,}")
            k5.metric("Inversión Meta", f"${costos['Inversion']:,.2f}")

            g1, g2 = st.columns([1.25, 1.05])
            with g1:
                _render_grafica_embudo(embudo, f"🔻 Embudo de Conversión — {mes_sel}")
            with g2:
                _render_medidor_salud(score_salud, estado_salud, justif_mercado, embudo, costos, bench, es_zae=False)

            st.markdown("---")
            _render_grafica_costos_barras(costos, f"💸 3. Costos Publicitarios y Rentabilidad — {mes_sel}")

            st.markdown("---")
            st.markdown(f"#### 🔥 Contenido Más Efectivo — {marca_activa} ({mes_sel})")
            _render_grafica_contenido_efectivo(contenidos_mes, marca_activa)

            hist_actual_marca = cfg.get("historial_anual", {}).get(marca_activa, {})
            _render_consultor_ia_resultados(
                db, marca_activa, mes_sel, embudo, costos, [], contenidos_mes, score_salud, justif_mercado, hist_actual_marca, es_zae=False
            )

        # ---------------------------------------------------------------------
        # COMPARATIVA HISTÓRICA ANUAL (INDEXADA POR TÍTULO DE MES)
        # ---------------------------------------------------------------------
        st.markdown("---")
        st.markdown(f"### 📅 Comparativa Histórica Anual — {marca_activa}")
        st.caption("Se organiza automáticamente por el **título del mes del reporte** (ej. Agosto, Septiembre, Octubre), sin importar qué día los guardes.")

        hist_marca = cfg.get("historial_anual", {}).get(marca_activa, {})
        if not hist_marca:
            st.info("Presiona **💾 Guardar en Comparativa Anual** arriba para acumular los meses y ver la evolución anual.")
        else:
            meses_ord = sorted(list(hist_marca.keys()), key=_clave_orden_mes)
            df_hist = pd.DataFrame([hist_marca[m] for m in meses_ord])

            h_c1, h_c2 = st.columns(2)
            with h_c1:
                fig_h_res = go.Figure()
                fig_h_res.add_trace(go.Bar(x=df_hist["mes_reporte"], y=df_hist["Resultados"], name="Leads WA", marker_color="#3B82F6", text=df_hist["Resultados"], textposition="auto"))
                if df_hist["Citas"].sum() > 0:
                    fig_h_res.add_trace(go.Bar(x=df_hist["mes_reporte"], y=df_hist["Citas"], name="Citas", marker_color="#F59E0B", text=df_hist["Citas"], textposition="auto"))
                if df_hist["Ventas"].sum() > 0:
                    fig_h_res.add_trace(go.Bar(x=df_hist["mes_reporte"], y=df_hist["Ventas"], name="Ventas", marker_color="#10B981", text=df_hist["Ventas"], textposition="auto"))
                fig_h_res.update_layout(title="📈 Evolución Mensual de Resultados", barmode="group", template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=360)
                st.plotly_chart(fig_h_res, use_container_width=True)

            with h_c2:
                fig_h_cost = go.Figure()
                fig_h_cost.add_trace(go.Scatter(x=df_hist["mes_reporte"], y=df_hist["CPL"], mode="lines+markers+text", name="CPL ($)", text=[f"${v:.2f}" for v in df_hist["CPL"]], textposition="top center", line=dict(color="#38BDF8", width=3)))
                if df_hist["CAC"].sum() > 0:
                    fig_h_cost.add_trace(go.Scatter(x=df_hist["mes_reporte"], y=df_hist["CAC"], mode="lines+markers+text", name="CAC ($)", text=[f"${v:.2f}" for v in df_hist["CAC"]], textposition="top center", line=dict(color="#EF4444", width=3)))
                fig_h_cost.update_layout(title="💸 Tendencia Anual de Costos (CPL / CAC)", template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=360)
                st.plotly_chart(fig_h_cost, use_container_width=True)

            st.dataframe(df_hist, width="stretch", hide_index=True)

    # =========================================================================
    # OPCIÓN 2: DESCARGA DIRECTA DESDE META ADS API EN LA APP (SIN GOOGLE SHEETS)
    # =========================================================================
    else:
        st.markdown(f"#### 🚀 Conexión Directa a Meta Marketing API — **{marca_activa}**")
        st.caption("Descarga los resultados de campañas y anuncios directamente en tu aplicación sin pasar por Google Sheets.")

        with st.expander("🔑 Permisos y Credenciales de Meta Ads (Por Marca)", expanded=not bool(creds_meta.get("meta_token"))):
            cm1, cm2 = st.columns(2)
            ad_acc_in = cm1.text_input("ID de Cuenta Publicitaria (Ad Account ID):", value=creds_meta.get("ad_account_id", ""), placeholder="Ej. act_123456789012345", key=f"ad_acc_m5_{marca_activa}")
            meta_tok_in = cm2.text_input("Token de Acceso Meta (Permiso ads_read):", value=creds_meta.get("meta_token", ""), type="password", placeholder="EAA...", key=f"meta_tok_m5_{marca_activa}")

            if st.button("💾 Guardar Credenciales de Meta Ads", key=f"save_meta_creds_m5_{marca_activa}"):
                creds_meta["ad_account_id"] = ad_acc_in.strip()
                creds_meta["meta_token"] = meta_tok_in.strip()
                guardar_datos(db)
                st.success(f"Permisos de Meta Ads guardados para {marca_activa}.")

        with st.container(border=True):
            st.markdown("**📥 Descargar Resultados de Meta Ads Directamente a la App**")
            d1, d2, d3 = st.columns([1.3, 1.3, 1.4])

            periodo_tipo = d1.selectbox("Periodo a descargar:", ["Últimos 30 días", "Mes específico", "Rango personalizado"], key=f"per_tipo_m5_{marca_activa}")

            hoy = date.today()
            if periodo_tipo == "Últimos 30 días":
                since_dt = hoy - timedelta(days=30)
                until_dt = hoy
                d2.info(f"Del **{since_dt.strftime('%d/%m/%Y')}** al **{until_dt.strftime('%d/%m/%Y')}**")
            elif periodo_tipo == "Mes específico":
                c_m1, c_m2 = d2.columns(2)
                mes_nom = c_m1.selectbox("Mes:", list(MESES_ES_MAP.keys()), index=hoy.month - 1, key=f"sel_m_meta_m5_{marca_activa}")
                anio_num = c_m2.number_input("Año:", min_value=2024, max_value=2030, value=hoy.year, key=f"sel_a_meta_m5_{marca_activa}")
                m_idx = MESES_ES_MAP[mes_nom]
                since_dt = date(int(anio_num), m_idx, 1)
                until_dt = date(int(anio_num), 12, 31) if m_idx == 12 else (date(int(anio_num), m_idx + 1, 1) - timedelta(days=1))
            else:
                c_r1, c_r2 = d2.columns(2)
                since_dt = c_r1.date_input("Inicio:", value=hoy - timedelta(days=15), key=f"r_ini_m5_{marca_activa}")
                until_dt = c_r2.date_input("Fin:", value=hoy, key=f"r_fin_m5_{marca_activa}")

            d3.write("")
            d3.write("")
            if d3.button("⬇️ Descargar desde Facebook a la App", type="primary", width="stretch", key=f"btn_dl_meta_m5_{marca_activa}"):
                try:
                    with st.spinner("Conectando con Meta Marketing API..."):
                        nuevos_registros = _descargar_insights_meta_directo(
                            ad_account_id=creds_meta.get("ad_account_id", ""),
                            access_token=creds_meta.get("meta_token", ""),
                            since_str=since_dt.strftime("%Y-%m-%d"),
                            until_str=until_dt.strftime("%Y-%m-%d"),
                            marca_nombre=marca_activa
                        )
                    cfg["meta_ads_data"][marca_activa] = nuevos_registros
                    guardar_datos(db)
                    st.success(f"¡Descargados {len(nuevos_registros)} registros directo en la app!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al conectar con Meta Ads: {e}")

        registros_meta = cfg.get("meta_ads_data", {}).get(marca_activa, [])
        if not registros_meta:
            st.info(f"Aún no has descargado datos directos de Meta Ads para **{marca_activa}**.")
            return

        df_meta = pd.DataFrame(registros_meta)
        resumen_mes = df_meta.groupby("MES").agg(
            Impresiones=("IMPRESIONES", "sum"),
            Alcance=("ALCANCE", "sum"),
            Resultados=("RESULTADOS", "sum"),
            Inversion=("GASTO", "sum")
        ).reset_index().sort_values("MES")
        resumen_mes["CPL"] = resumen_mes.apply(lambda r: round(r["Inversion"] / r["Resultados"], 2) if r["Resultados"] > 0 else 0.0, axis=1)

        embudo_m2 = {
            "Impresiones": float(resumen_mes["Impresiones"].sum()),
            "Alcance": float(resumen_mes["Alcance"].sum()),
            "Resultados (WhatsApp)": float(resumen_mes["Resultados"].sum()),
            "Citas Asistidas": 0.0,
            "Ventas Concretadas": 0.0
        }
        tot_inv_m2 = float(resumen_mes["Inversion"].sum())
        tot_res_m2 = float(resumen_mes["Resultados"].sum())
        costos_m2 = {
            "Inversion": tot_inv_m2,
            "CPL": round(tot_inv_m2 / tot_res_m2, 2) if tot_res_m2 > 0 else 0.0,
            "CPAC": 0.0,
            "CAC": 0.0
        }

        score_m2, estado_m2, justif_m2, bench_m2 = _calcular_salud_inversion(embudo_m2, costos_m2, es_zae=False, marca_nombre=marca_activa)

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Alcance Total", f"{int(embudo_m2['Alcance']):,}")
        k2.metric("Resultados Totales", f"{int(embudo_m2['Resultados (WhatsApp)']):,}")
        k3.metric("Inversión Total", f"${costos_m2['Inversion']:,.2f}")
        k4.metric("CPL Promedio", f"${costos_m2['CPL']:,.2f}")

        _render_medidor_salud(score_m2, estado_m2, justif_m2, embudo_m2, costos_m2, bench_m2, es_zae=False)
        st.dataframe(resumen_mes, width="stretch", hide_index=True)

        top_ads = df_meta.groupby("ANUNCIO").agg(
            Resultados=("RESULTADOS", "sum"),
            Impresiones=("IMPRESIONES", "sum"),
            Inversion=("GASTO", "sum")
        ).reset_index()
        top_ads["Costo / Res."] = top_ads.apply(lambda r: round(r["Inversion"] / r["Resultados"], 2) if r["Resultados"] > 0 else 0.0, axis=1)
        top_ads = top_ads.sort_values(by="Resultados", ascending=False).head(8)

        contenidos_m2 = [
            {
                "Nombre del Anuncio": r["ANUNCIO"],
                "Conjunto": "Meta Ads API",
                "Resultados": int(r["Resultados"]),
                "Costo / Res.": float(r["Costo / Res."]),
                "Impresiones": int(r["Impresiones"]),
                "Alcance": 0,
                "Creatividad": ""
            }
            for _, r in top_ads.iterrows()
        ]

        fig_m2 = px.bar(top_ads, x="Resultados", y="ANUNCIO", orientation="h", text="Resultados", color="Costo / Res.", color_continuous_scale="Tealgrn_r", title=f"🔥 Top Anuncios Descargados — {marca_activa}")
        fig_m2.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis={"categoryorder": "total ascending"}, height=400)
        st.plotly_chart(fig_m2, use_container_width=True)

        hist_actual_marca = cfg.get("historial_anual", {}).get(marca_activa, {})
        _render_consultor_ia_resultados(
            db, marca_activa, "Meta Ads Directo", embudo_m2, costos_m2, [], contenidos_m2, score_m2, justif_m2, hist_actual_marca, es_zae=False
        )