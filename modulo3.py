# modulos/modulo3.py
import io
import os
import re
import uuid
import time
import threading
from datetime import datetime, date, timedelta
from PIL import Image
import requests
import pandas as pd
import streamlit as st
from storage import cargar_datos, guardar_datos

CARPETA_MEDIA_CAL = "media_calendario"
os.makedirs(CARPETA_MEDIA_CAL, exist_ok=True)

EXTENSIONES_VIDEO = (".mp4", ".mov", ".avi", ".webm", ".mkv")


def _normalizar_texto(texto):
    """Empata nombres de marca como 'Zona Auto Estrena' con 'ZONA AUTOESTRENA'."""
    if pd.isna(texto):
        return ""
    return re.sub(r"[^a-z0-9]", "", str(texto).lower())


def _limpiar_id(valor):
    """Quita el '.0' cuando Excel/Pandas lee IDs numéricos como decimales."""
    if pd.isna(valor) or not str(valor).strip():
        return ""
    txt = str(valor).strip()
    return txt[:-2] if txt.endswith(".0") else txt


def _convertir_url_sheet_a_csv(url):
    """Convierte una URL estándar de Google Sheets en exportación directa CSV."""
    match_id = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if not match_id:
        return None
    sheet_id = match_id.group(1)
    match_gid = re.search(r"[#&?]gid=([0-9]+)", url)
    gid_param = f"&gid={match_gid.group(1)}" if match_gid else ""
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv{gid_param}"


def _es_video(ruta_o_url):
    """Detecta si el archivo corresponde a un video."""
    if not ruta_o_url:
        return False
    return str(ruta_o_url).lower().split("?")[0].endswith(EXTENSIONES_VIDEO)


@st.cache_data(ttl=3600, show_spinner=False)
def _obtener_bytes_imagen(url_o_ruta):
    """
    Descarga los bytes de la imagen desde Google Drive o URL externa en segundo plano
    para evitar bloqueos CORS/cookies del navegador.
    """
    if not url_o_ruta or pd.isna(url_o_ruta):
        return None

    src = str(url_o_ruta).strip()
    if not src:
        return None

    # Si es un archivo local subido a la plataforma
    if os.path.exists(src):
        with open(src, "rb") as f:
            return f.read()

    if not src.startswith("http"):
        return None

    headers = {"User-Agent": "Mozilla/5.0"}
    candidatos = []

    # Detectar si es un enlace de Google Drive y probar sus endpoints directos
    match_drive = re.search(r"(?:id=|/d/)([a-zA-Z0-9_-]{20,})", src)
    if "drive.google.com" in src and match_drive:
        file_id = match_drive.group(1)
        candidatos = [
            f"https://drive.google.com/uc?export=download&id={file_id}",
            f"https://drive.usercontent.google.com/download?id={file_id}&export=download",
            f"https://lh3.googleusercontent.com/d/{file_id}=w800",
            f"https://drive.google.com/thumbnail?id={file_id}&sz=w800",
        ]
    else:
        candidatos = [src]

    for url_cand in candidatos:
        try:
            resp = requests.get(url_cand, headers=headers, timeout=10, allow_redirects=True)
            if resp.status_code == 200 and resp.content:
                # Validar que realmente sea una imagen válida y no una página HTML de login
                img = Image.open(io.BytesIO(resp.content))
                img.verify()
                return resp.content
        except Exception:
            continue

    return None


def _parsear_fecha_hora(texto_fh):
    """Convierte textos de fecha/hora a objeto datetime."""
    formatos = ["%d/%m/%Y %I:%M %p", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M"]
    for fmt in formatos:
        try:
            return datetime.strptime(str(texto_fh).strip(), fmt)
        except ValueError:
            continue
    return None


def _publicar_en_facebook(page_id, access_token, copy_texto, ruta_o_url, timestamp_programado=None):
    """Publica o programa una imagen o video en una Página de Facebook mediante Meta Graph API."""
    if not page_id or not access_token:
        raise ValueError("Falta PAGE_ID FACEBOOK o el Token de Acceso de Página.")

    es_vid = _es_video(ruta_o_url)
    es_local = bool(ruta_o_url) and os.path.exists(str(ruta_o_url))

    payload = {"access_token": access_token}

    if timestamp_programado:
        payload["published"] = "false"
        payload["scheduled_publish_time"] = str(int(timestamp_programado))
    else:
        payload["published"] = "true"

    if es_vid:
        if not es_local:
            raise ValueError("Para publicar video directo en Facebook sube el archivo local (.mp4 / .mov).")
        url_api = f"https://graph-video.facebook.com/v21.0/{page_id}/videos"
        payload["description"] = copy_texto
        with open(ruta_o_url, "rb") as f:
            resp = requests.post(url_api, data=payload, files={"source": f}, timeout=120)
    elif es_local:
        url_api = f"https://graph.facebook.com/v21.0/{page_id}/photos"
        payload["caption"] = copy_texto
        with open(ruta_o_url, "rb") as f:
            resp = requests.post(url_api, data=payload, files={"source": f}, timeout=60)
    elif str(ruta_o_url).startswith("http"):
        url_final = str(ruta_o_url).strip()
        match_drive = re.search(r"(?:id=|/d/)([a-zA-Z0-9_-]{20,})", url_final)
        if "drive.google.com" in url_final and match_drive:
            url_final = f"https://drive.google.com/uc?export=download&id={match_drive.group(1)}"
        url_api = f"https://graph.facebook.com/v21.0/{page_id}/photos"
        payload["url"] = url_final
        payload["caption"] = copy_texto
        resp = requests.post(url_api, data=payload, timeout=60)
    else:
        url_api = f"https://graph.facebook.com/v21.0/{page_id}/feed"
        payload["message"] = copy_texto
        resp = requests.post(url_api, data=payload, timeout=30)

    data = resp.json()
    if "error" in data:
        msg_err = data["error"].get("message", "Error desconocido en Meta API")
        raise RuntimeError(msg_err)
    return data


def _ciclo_publicador_automatico():
    """Hilo en segundo plano tipo Make: publica posts pendientes cuando llega su fecha y hora."""
    while True:
        try:
            db_disk = cargar_datos()
            cal_nativo = db_disk.get("calendario_nativo", {})
            cfg_redes = db_disk.get("config_redes", {})
            ahora = datetime.now()
            hubo_cambios = False

            for marca_k, lista_posts in cal_nativo.items():
                cred = cfg_redes.get(marca_k, {})
                if not cred.get("auto_publicar_activo", False):
                    continue

                page_id = cred.get("page_id_fb", "")
                token_fb = cred.get("fb_access_token", "")
                if not page_id or not token_fb:
                    continue

                for post in lista_posts:
                    estado_actual = str(post.get("ESTADO", "")).lower()
                    if estado_actual == "pendiente":
                        dt_prog = _parsear_fecha_hora(post.get("HORARIO_FACEBOOK", ""))
                        if dt_prog and ahora >= dt_prog:
                            try:
                                _publicar_en_facebook(
                                    page_id=page_id,
                                    access_token=token_fb,
                                    copy_texto=post.get("COPY_FACEBOOK", ""),
                                    ruta_o_url=post.get("URL_IMAGEN", ""),
                                    timestamp_programado=None
                                )
                                post["ESTADO"] = "Publicado"
                                post["NOTA_API"] = f"Publicado auto: {ahora.strftime('%d/%m %H:%M')}"
                            except Exception as e:
                                post["ESTADO"] = "Error API"
                                post["NOTA_API"] = str(e)
                            hubo_cambios = True

            if hubo_cambios:
                guardar_datos(db_disk)
        except Exception:
            pass
        time.sleep(30)


@st.cache_resource
def iniciar_motor_publicaciones():
    """Arranca una única instancia del publicador automático en segundo plano."""
    hilo = threading.Thread(target=_ciclo_publicador_automatico, daemon=True)
    hilo.start()
    return hilo


def _render_indicadores_y_alerta(total, publicados, pendientes, etiqueta_marca):
    """Muestra indicadores de porcentaje, conteo exacto y alertas de atención."""
    porcentaje_pub = (publicados / total * 100) if total > 0 else 0.0
    porcentaje_pend = (pendientes / total * 100) if total > 0 else 0.0

    st.markdown(f"#### 📊 Estado de Parrilla — {etiqueta_marca}")

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Programadas", f"{total}")
    k2.metric("Publicadas / Agendadas", f"{publicados}", f"{porcentaje_pub:.1f}% completado")
    k3.metric("Pendientes por Salir", f"{pendientes}", f"{porcentaje_pend:.1f}% restante", delta_color="off")
    k4.metric("Faltantes", f"Faltan {pendientes} de {total}")

    st.progress(min(porcentaje_pub / 100.0, 1.0))

    if total == 0:
        st.info("No hay publicaciones registradas para esta selección.")
    elif pendientes == 0:
        st.error(f"🚨 **Parrilla al 100%:** Ya salieron o quedaron agendadas las {total} publicaciones de **{etiqueta_marca}**. Es momento de preparar la nueva tanda.")
    elif pendientes <= 3 or porcentaje_pub >= 85:
        st.warning(f"⚠️ **Atención requerida:** Solo faltan **{pendientes} publicaciones de {total}** ({porcentaje_pend:.1f}% pendiente). Ve generando nuevo contenido para **{etiqueta_marca}**.")
    else:
        st.success(f"✅ **Buen ritmo:** Faltan **{pendientes} publicaciones pendientes de {total}** ({porcentaje_pub:.1f}% completado).")


def _render_tarjetas_publicaciones(df, es_local=False, db=None, marca_activa=None):
    """Renderiza tarjetas visuales con imagen o video, horarios, copys y acciones."""
    filtro_estado = st.radio(
        "Filtrar galería por estado:",
        ["⏳ Pendientes", "✅ Publicados / Agendados", "📋 Todos"],
        horizontal=True,
        key=f"filtro_est_{'local' if es_local else 'sheet'}_{marca_activa}"
    )

    df_vista = df.copy()
    if filtro_estado == "⏳ Pendientes":
        df_vista = df_vista[df_vista["ESTADO_NORM"].str.contains("pendiente|error", na=False)]
    elif filtro_estado == "✅ Publicados / Agendados":
        df_vista = df_vista[df_vista["ESTADO_NORM"].str.contains("publicado|programado", na=False)]

    if df_vista.empty:
        st.info("No hay publicaciones en esta categoría.")
        return

    for _, row in df_vista.iterrows():
        estado_raw = str(row.get("ESTADO", "Pendiente")).strip()
        es_pub = any(w in estado_raw.lower() for w in ["publicado", "programado"])
        icono = "✅" if es_pub else ("❌" if "error" in estado_raw.lower() else "⏳")
        url_media = str(row.get("URL_IMAGEN", "")).strip() if pd.notna(row.get("URL_IMAGEN")) else ""

        with st.container(border=True):
            c_media, c_info = st.columns([1.2, 2.8], gap="medium")

            with c_media:
                if url_media:
                    if _es_video(url_media):
                        try:
                            st.video(url_media)
                        except Exception:
                            st.caption("⚠️ Vista previa de video no disponible")
                    else:
                        img_bytes = _obtener_bytes_imagen(url_media)
                        if img_bytes:
                            st.image(img_bytes, width="stretch")
                        else:
                            st.warning("🔒 No se pudo cargar la vista previa (verifica que la carpeta de Drive sea pública).")

                    if url_media.startswith("http"):
                        st.caption(f"[Abrir archivo original]({url_media})")
                else:
                    st.info("Sin archivo multimedia")

            with c_info:
                top_a, top_b = st.columns([3, 1])
                top_a.markdown(f"**{icono} {estado_raw.upper()}** | 🏢 `{row.get('MARCA', marca_activa)}`")
                
                fb_id_limpio = _limpiar_id(row.get("PAGE_ID FACEBOOK", ""))
                if row.get("ARCHIVO_NOMBRE"):
                    top_b.caption(f"📎 `{row.get('ARCHIVO_NOMBRE')}`")
                elif fb_id_limpio:
                    top_b.caption(f"FB ID: `{fb_id_limpio}`")

                if row.get("NOTA_API"):
                    st.caption(f"ℹ️ {row.get('NOTA_API')}")

                h_col1, h_col2 = st.columns(2)
                h_col1.caption(f"📘 **Horario FB:** {row.get('HORARIO_FACEBOOK', 'Sin fecha')}")
                h_col2.caption(f"📸 **Horario IG:** {row.get('HORARIO_INSTAGRAM', 'Sin fecha')}")

                tab_fb, tab_ig = st.tabs(["Copy Facebook", "Copy Instagram"])
                with tab_fb:
                    st.write(row.get("COPY_FACEBOOK", "") if pd.notna(row.get("COPY_FACEBOOK")) else "*Sin copy*")
                with tab_ig:
                    st.write(row.get("COPY_INSTAGRAM", "") if pd.notna(row.get("COPY_INSTAGRAM")) else "*Sin copy*")

                if es_local and db is not None:
                    b1, b2, b3 = st.columns(3)
                    
                    if b1.button("🚀 Publicar ahora en FB", key=f"pub_now_{row['ID']}"):
                        cred = db.get("config_redes", {}).get(marca_activa, {})
                        try:
                            with st.spinner("Subiendo publicación a Facebook..."):
                                _publicar_en_facebook(
                                    page_id=cred.get("page_id_fb", ""),
                                    access_token=cred.get("fb_access_token", ""),
                                    copy_texto=row.get("COPY_FACEBOOK", ""),
                                    ruta_o_url=url_media,
                                    timestamp_programado=None
                                )
                            for item in db["calendario_nativo"][marca_activa]:
                                if item["ID"] == row["ID"]:
                                    item["ESTADO"] = "Publicado"
                                    item["NOTA_API"] = f"Publicado manual: {datetime.now().strftime('%d/%m %H:%M')}"
                            guardar_datos(db)
                            st.success("¡Publicado en vivo en Facebook!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al publicar en FB: {e}")

                    nuevo_estado = "Pendiente" if es_pub else "Publicado"
                    if b2.button(f"Marcar {nuevo_estado}", key=f"tog_loc_{row['ID']}"):
                        for item in db["calendario_nativo"][marca_activa]:
                            if item["ID"] == row["ID"]:
                                item["ESTADO"] = nuevo_estado
                        guardar_datos(db)
                        st.rerun()

                    if b3.button("🗑️ Eliminar", key=f"del_loc_{row['ID']}"):
                        if url_media and os.path.exists(url_media):
                            try:
                                os.remove(url_media)
                            except Exception:
                                pass
                        db["calendario_nativo"][marca_activa] = [
                            item for item in db["calendario_nativo"][marca_activa] if item["ID"] != row["ID"]
                        ]
                        guardar_datos(db)
                        st.rerun()


def render():
    iniciar_motor_publicaciones()

    db_disk = cargar_datos()
    if "calendario_nativo" in db_disk:
        st.session_state.db["calendario_nativo"] = db_disk["calendario_nativo"]

    db = st.session_state.db
    marca_activa = db["marca_activa"]
    todas_las_marcas = list(db["marcas"].keys())

    st.subheader(f"🗓️ Programación de Publicaciones — {marca_activa}")

    if "config_calendario" not in db:
        db["config_calendario"] = {
            "google_sheet_url": "",
            "marcas_asociadas": [marca_activa]
        }
    if "calendario_nativo" not in db:
        db["calendario_nativo"] = {}
    if marca_activa not in db["calendario_nativo"]:
        db["calendario_nativo"][marca_activa] = []

    modo = st.radio(
        "Selecciona modalidad de trabajo:",
        [
            "📊 Opción 1: Monitor Google Sheets / Excel (Tus hojas actuales)",
            "⚡ Opción 2: Generador por Lote + Publicador Directo Facebook"
        ],
        horizontal=True
    )

    st.markdown("---")

    # =========================================================================
    # OPCIÓN 1: MONITOR DE GOOGLE SHEETS / EXCEL
    # =========================================================================
    if modo.startswith("📊"):
        cfg_cal = db["config_calendario"]

        with st.expander("🔗 Enlace Permanente y Asociación de Marcas (Google Sheets / Excel)", expanded=not bool(cfg_cal.get("google_sheet_url"))):
            url_input = st.text_input(
                "Enlace de Google Sheets:",
                value=cfg_cal.get("google_sheet_url", ""),
                placeholder="https://docs.google.com/spreadsheets/d/..."
            )

            marcas_asoc_default = [m for m in cfg_cal.get("marcas_asociadas", []) if m in todas_las_marcas]
            marcas_asociadas = st.multiselect(
                "Asociar este archivo con las siguientes marcas:",
                todas_las_marcas,
                default=marcas_asoc_default,
                help="Al cambiar de marca en el menú izquierdo, la app filtrará automáticamente sus publicaciones desde este mismo enlace."
            )

            col_b1, col_b2 = st.columns(2)
            if col_b1.button("💾 Guardar Enlace y Asociación", type="primary", width="stretch"):
                cfg_cal["google_sheet_url"] = url_input.strip()
                cfg_cal["marcas_asociadas"] = marcas_asociadas
                guardar_datos(db)
                st.success("Enlace y marcas asociadas guardados.")
                st.rerun()

            archivo_excel = col_b2.file_uploader(
                "O sube un archivo Excel / CSV (.xlsx, .csv):",
                type=["xlsx", "csv"],
                key="upload_excel_cal"
            )

        url_guardada = cfg_cal.get("google_sheet_url", "")
        esta_asociada = marca_activa in cfg_cal.get("marcas_asociadas", [])

        df_raw = None
        if archivo_excel is not None:
            try:
                df_raw = pd.read_csv(archivo_excel) if archivo_excel.name.endswith(".csv") else pd.read_excel(archivo_excel)
            except Exception as e:
                st.error(f"Error al leer el archivo: {e}")

        elif url_guardada:
            if not esta_asociada:
                st.warning(f"La marca **{marca_activa}** no está asociada al enlace guardado. Selecciónala arriba en 'Asociar este archivo' y guarda.")
            else:
                csv_url = _convertir_url_sheet_a_csv(url_guardada)
                if not csv_url:
                    st.error("URL de Google Sheets no válida.")
                else:
                    c_ref1, c_ref2 = st.columns([4, 1])
                    c_ref1.caption("Sincronizado con tu Google Sheet.")
                    if c_ref2.button("🔄 Actualizar datos"):
                        st.cache_data.clear()
                        st.rerun()
                    try:
                        df_raw = pd.read_csv(csv_url)
                    except Exception as e:
                        st.error(f"No se pudo leer la hoja. Verifica permisos de lectura pública. Detalle: {e}")

        if df_raw is not None and not df_raw.empty:
            df_raw.columns = [str(c).strip().upper() for c in df_raw.columns]

            if "ESTADO" not in df_raw.columns or "MARCA" not in df_raw.columns:
                st.error("La hoja debe contener las columnas 'MARCA' y 'ESTADO'.")
            else:
                df_limpio = df_raw[df_raw["ESTADO"].notna() & (df_raw["ESTADO"].astype(str).str.strip() != "")].copy()
                df_limpio["MARCA_NORM"] = df_limpio["MARCA"].apply(_normalizar_texto)
                df_limpio["ESTADO_NORM"] = df_limpio["ESTADO"].astype(str).str.lower().str.strip()

                alcance = st.radio(
                    "Alcance del reporte:",
                    [f"Solo marca activa ({marca_activa})", "Todas las marcas del archivo (Prioridades)"],
                    horizontal=True
                )

                if alcance.startswith("Solo marca"):
                    norm_activa = _normalizar_texto(marca_activa)
                    df_filtrado = df_limpio[df_limpio["MARCA_NORM"] == norm_activa]
                    etiqueta = marca_activa
                else:
                    df_filtrado = df_limpio
                    etiqueta = "Todas las marcas del archivo"

                total = len(df_filtrado)
                publicados = int(df_filtrado["ESTADO_NORM"].str.contains("publicado", na=False).sum())
                pendientes = int(df_filtrado["ESTADO_NORM"].str.contains("pendiente", na=False).sum())

                _render_indicadores_y_alerta(total, publicados, pendientes, etiqueta)

                if not alcance.startswith("Solo marca") and not df_limpio.empty:
                    st.markdown("##### 🎯 Comparativa rápida por marca (¿Dónde enfocar atención?)")
                    resumen_marcas = []
                    for m_nombre, grupo in df_limpio.groupby("MARCA"):
                        tot_m = len(grupo)
                        pub_m = int(grupo["ESTADO_NORM"].str.contains("publicado", na=False).sum())
                        pen_m = int(grupo["ESTADO_NORM"].str.contains("pendiente", na=False).sum())
                        pct_m = (pub_m / tot_m * 100) if tot_m > 0 else 0
                        resumen_marcas.append({
                            "Marca": m_nombre,
                            "Total": tot_m,
                            "Publicadas": pub_m,
                            "Pendientes": pen_m,
                            "Avance": f"{pct_m:.1f}%",
                            "Prioridad": "🚨 Crear contenido ya" if pen_m <= 3 else "✅ En orden"
                        })
                    st.dataframe(pd.DataFrame(resumen_marcas), width="stretch", hide_index=True)

                st.markdown("---")
                _render_tarjetas_publicaciones(df_filtrado, es_local=False, marca_activa=marca_activa)

    # =========================================================================
    # OPCIÓN 2: GENERADOR POR LOTE + PUBLICACIÓN AUTOMÁTICA EN FACEBOOK
    # =========================================================================
    else:
        if "config_redes" not in db:
            db["config_redes"] = {}
        if marca_activa not in db["config_redes"]:
            db["config_redes"][marca_activa] = {
                "page_id_fb": "",
                "page_id_ig": "",
                "fb_access_token": "",
                "auto_publicar_activo": False,
                "banco_copys_fb": "",
                "banco_copys_ig": ""
            }

        cfg_redes = db["config_redes"][marca_activa]

        with st.expander("🔑 Conexión Directa con Facebook (Page ID y Token)", expanded=not bool(cfg_redes.get("fb_access_token"))):
            c_id1, c_id2 = st.columns(2)
            fb_id_in = c_id1.text_input("PAGE_ID FACEBOOK:", value=cfg_redes.get("page_id_fb", ""), placeholder="Ej. 103719365811152")
            ig_id_in = c_id2.text_input("PAGE_ID INSTAGRAM (opcional):", value=cfg_redes.get("page_id_ig", ""), placeholder="Ej. 17841457221702933")
            
            fb_tok_in = st.text_input(
                "Token de Acceso de Página de Facebook (Meta Graph API):",
                value=cfg_redes.get("fb_access_token", ""),
                type="password",
                placeholder="EAA..."
            )
            auto_chk = st.checkbox(
                "🤖 Activar disparador automático en segundo plano (publica al llegar la hora mientras la app esté abierta)",
                value=cfg_redes.get("auto_publicar_activo", False)
            )

            if st.button("💾 Guardar Conexión Facebook"):
                cfg_redes["page_id_fb"] = fb_id_in.strip()
                cfg_redes["page_id_ig"] = ig_id_in.strip()
                cfg_redes["fb_access_token"] = fb_tok_in.strip()
                cfg_redes["auto_publicar_activo"] = auto_chk
                guardar_datos(db)
                st.success(f"Configuración de Facebook guardada para {marca_activa}.")

        with st.expander("⚡ Armar Parrilla Completa de un Solo Golpe (Imágenes/Videos + Copys + Horarios)", expanded=True):
            st.caption("Sube tus imágenes o videos enumerados (ej. `01.jpg`, `02.mp4`, `03x.jpg`), define tu banco de copys y genera toda la programación automáticamente.")

            archivos_lote = st.file_uploader(
                "1️⃣ Sube el lote de imágenes y/o videos (se ordenan automáticamente por nombre):",
                type=["png", "jpg", "jpeg", "webp", "mp4", "mov"],
                accept_multiple_files=True,
                key=f"batch_files_{marca_activa}"
            )

            if archivos_lote:
                nombres_ord = sorted([f.name for f in archivos_lote], key=lambda x: x.lower())
                st.info(f"📁 **{len(nombres_ord)} archivo(s) listos en orden:** {', '.join(nombres_ord[:8])}{'...' if len(nombres_ord) > 8 else ''}")

            st.markdown("**2️⃣ Banco de Copys para rotar** *(separa cada copy distinto con una línea que diga `---`)*")
            
            res_mod2 = st.session_state.get(f"res_contenido_{marca_activa}", {})
            if res_mod2.get("copys"):
                if st.button("📥 Importar copys generados en Módulo 2"):
                    cfg_redes["banco_copys_fb"] = res_mod2["copys"]
                    guardar_datos(db)
                    st.rerun()

            b_c1, b_c2 = st.columns(2)
            txt_copys_fb = b_c1.text_area(
                "Copys Facebook (separados por ---):",
                value=cfg_redes.get("banco_copys_fb", ""),
                height=160,
                placeholder="Copy 1 para Facebook...\n---\nCopy 2 (Especial para archivos con 'x' al final)...\n---\nCopy 3..."
            )
            txt_copys_ig = b_c2.text_area(
                "Copys Instagram (opcional, si está vacío usa los de FB):",
                value=cfg_redes.get("banco_copys_ig", ""),
                height=160,
                placeholder="Copy 1 para Instagram...\n---\nCopy 2..."
            )

            regla_x = st.checkbox(
                "Aplicar regla especial de archivo terminado en 'x' (asigna el Copy #2 exclusivamente a archivos como 03x.jpg)",
                value=False
            )

            st.markdown("**3️⃣ Regla de Fechas y Horarios Rotativos**")
            r_c1, r_c2, r_c3 = st.columns(3)
            fecha_inicio = r_c1.date_input("Iniciar programación desde:", value=date.today() + timedelta(days=1))
            horarios_str = r_c2.text_input(
                "Horarios a rotar (separados por coma):",
                value="10:00 AM, 12:00 PM, 03:00 PM, 06:00 PM"
            )
            posts_por_dia = r_c3.number_input("Publicaciones por día:", min_value=1, max_value=6, value=1)

            col_gen1, col_gen2 = st.columns([2, 1])
            if col_gen1.button("⚡ Generar Toda la Parrilla de un Solo Golpe", type="primary", width="stretch"):
                if not archivos_lote:
                    st.warning("Sube al menos una imagen o video en el paso 1.")
                elif not txt_copys_fb.strip():
                    st.warning("Escribe al menos un copy en el banco de Copys Facebook.")
                else:
                    cfg_redes["banco_copys_fb"] = txt_copys_fb.strip()
                    cfg_redes["banco_copys_ig"] = txt_copys_ig.strip()

                    lista_copys_fb = [c.strip() for c in txt_copys_fb.split("---") if c.strip()]
                    lista_copys_ig = [c.strip() for c in txt_copys_ig.split("---") if c.strip()] or lista_copys_fb
                    lista_horas = [h.strip() for h in horarios_str.split(",") if h.strip()] or ["10:00 AM"]

                    fb_normales = [c for idx, c in enumerate(lista_copys_fb) if idx != 1] or lista_copys_fb
                    ig_normales = [c for idx, c in enumerate(lista_copys_ig) if idx != 1] or lista_copys_ig
                    idx_normal = 0

                    archivos_ordenados = sorted(archivos_lote, key=lambda f: f.name.lower())
                    fecha_cursor = fecha_inicio

                    for k, archivo in enumerate(archivos_ordenados):
                        nombre_base = os.path.splitext(archivo.name)[0].strip()
                        termina_en_x = bool(re.search(r"[xX]$", nombre_base))

                        nombre_unico = f"{uuid.uuid4().hex[:10]}_{archivo.name}"
                        ruta_guardada = os.path.join(CARPETA_MEDIA_CAL, nombre_unico)
                        with open(ruta_guardada, "wb") as f:
                            f.write(archivo.getbuffer())

                        dia_offset = k // posts_por_dia
                        fecha_post = fecha_cursor + timedelta(days=dia_offset)
                        hora_asignada = lista_horas[k % len(lista_horas)]
                        fecha_hora_final = f"{fecha_post.strftime('%d/%m/%Y')} {hora_asignada}"

                        if regla_x and termina_en_x:
                            c_fb = lista_copys_fb[1] if len(lista_copys_fb) > 1 else lista_copys_fb[0]
                            c_ig = lista_copys_ig[1] if len(lista_copys_ig) > 1 else lista_copys_ig[0]
                        elif regla_x:
                            c_fb = fb_normales[idx_normal % len(fb_normales)]
                            c_ig = ig_normales[idx_normal % len(ig_normales)]
                            idx_normal += 1
                        else:
                            c_fb = lista_copys_fb[k % len(lista_copys_fb)]
                            c_ig = lista_copys_ig[k % len(lista_copys_ig)]

                        db["calendario_nativo"][marca_activa].append({
                            "ID": uuid.uuid4().hex[:8],
                            "MARCA": marca_activa.upper(),
                            "ARCHIVO_NOMBRE": archivo.name,
                            "PAGE_ID FACEBOOK": cfg_redes.get("page_id_fb", ""),
                            "PAGE_ID INSTAGRAM": cfg_redes.get("page_id_ig", ""),
                            "COPY_FACEBOOK": c_fb,
                            "COPY_INSTAGRAM": c_ig,
                            "HORARIO_FACEBOOK": fecha_hora_final,
                            "HORARIO_INSTAGRAM": fecha_hora_final,
                            "URL_IMAGEN": ruta_guardada,
                            "ESTADO": "Pendiente",
                            "NOTA_API": ""
                        })

                    guardar_datos(db)
                    st.success(f"¡Listo! Se armaron {len(archivos_ordenados)} publicaciones automáticamente para {marca_activa}.")
                    st.rerun()

            if col_gen2.button("🗑️ Vaciar parrilla de esta marca", width="stretch"):
                for item in db["calendario_nativo"][marca_activa]:
                    ruta_f = str(item.get("URL_IMAGEN", ""))
                    if ruta_f and os.path.exists(ruta_f):
                        try:
                            os.remove(ruta_f)
                        except Exception:
                            pass
                db["calendario_nativo"][marca_activa] = []
                guardar_datos(db)
                st.rerun()

        lista_nativa = db["calendario_nativo"][marca_activa]
        if lista_nativa:
            df_nat = pd.DataFrame(lista_nativa)
            df_nat["ESTADO_NORM"] = df_nat["ESTADO"].astype(str).str.lower().str.strip()

            total_n = len(df_nat)
            pub_n = int(df_nat["ESTADO_NORM"].str.contains("publicado|programado", na=False).sum())
            pen_n = int(df_nat["ESTADO_NORM"].str.contains("pendiente|error", na=False).sum())

            _render_indicadores_y_alerta(total_n, pub_n, pen_n, marca_activa)

            if pen_n > 0:
                st.markdown("---")
                if st.button(f"🚀 Programar las {pen_n} publicaciones pendientes directo en Facebook (Un solo golpe)", type="primary"):
                    page_id = cfg_redes.get("page_id_fb", "")
                    token_fb = cfg_redes.get("fb_access_token", "")
                    if not page_id or not token_fb:
                        st.error("Primero guarda tu PAGE_ID FACEBOOK y Token de Acceso en el desplegable superior.")
                    else:
                        agendadas_ok = 0
                        errores_lote = []
                        ahora_ts = datetime.now().timestamp()

                        with st.spinner("Enviando lote programado a los servidores de Facebook..."):
                            for item in db["calendario_nativo"][marca_activa]:
                                if str(item.get("ESTADO", "")).lower() == "pendiente":
                                    dt_obj = _parsear_fecha_hora(item.get("HORARIO_FACEBOOK", ""))
                                    if not dt_obj:
                                        errores_lote.append(f"{item.get('ARCHIVO_NOMBRE', item['ID'])}: Fecha inválida")
                                        continue
                                    ts_prog = dt_obj.timestamp()
                                    if ts_prog < (ahora_ts + 900):
                                        errores_lote.append(f"{item.get('ARCHIVO_NOMBRE', item['ID'])}: La hora debe ser al menos 15 min en el futuro")
                                        continue
                                    try:
                                        _publicar_en_facebook(
                                            page_id=page_id,
                                            access_token=token_fb,
                                            copy_texto=item.get("COPY_FACEBOOK", ""),
                                            ruta_o_url=item.get("URL_IMAGEN", ""),
                                            timestamp_programado=ts_prog
                                        )
                                        item["ESTADO"] = "Programado en FB"
                                        item["NOTA_API"] = "Agendado en Meta Business Suite"
                                        agendadas_ok += 1
                                    except Exception as e:
                                        item["ESTADO"] = "Error API"
                                        item["NOTA_API"] = str(e)
                                        errores_lote.append(f"{item.get('ARCHIVO_NOMBRE', item['ID'])}: {e}")

                        guardar_datos(db)
                        if agendadas_ok > 0:
                            st.success(f"✅ ¡{agendadas_ok} publicaciones quedaron programadas directamente en Facebook!")
                        if errores_lote:
                            st.warning("Algunas publicaciones tuvieron observaciones:\n- " + "\n- ".join(errores_lote))
                        st.rerun()

            st.markdown("---")
            _render_tarjetas_publicaciones(df_nat, es_local=True, db=db, marca_activa=marca_activa)
        else:
            st.info(f"Aún no has armado una parrilla interna para **{marca_activa}**. Usa el panel superior para subir tus archivos y generar todo el lote.")