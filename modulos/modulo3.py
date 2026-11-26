# modulos/modulo3.py
import os
import re
import uuid
import time
import threading
import requests
import pandas as pd
import streamlit as st
from datetime import datetime, date
from storage import (
    cargar_datos,
    guardar_datos,
    listar_todos_los_user_ids,
    obtener_carpeta_media_usuario,
)

EXTENSIONES_VIDEO = (".mp4", ".mov", ".avi", ".webm", ".mkv")


def _es_url_publica(valor: str) -> bool:
    if not valor:
        return False
    return bool(re.match(r"^https?://", str(valor).strip(), re.IGNORECASE))


def _es_video(ruta_o_url: str) -> bool:
    if not ruta_o_url:
        return False
    limpio = str(ruta_o_url).split("?")[0].lower()
    return limpio.endswith(EXTENSIONES_VIDEO)


def _parsear_fecha_hora(texto_horario: str):
    if not texto_horario:
        return None
    s = str(texto_horario).strip()
    formatos = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
    ]
    for fmt in formatos:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _publicar_en_facebook(page_id: str, access_token: str, copy_texto: str, ruta_o_url: str = "", timestamp_programado: int | None = None) -> dict:
    """Publica o programa en Facebook Graph API (soporta texto, foto y video)."""
    if not page_id or not access_token:
        raise ValueError("Falta Page ID o Access Token de Facebook.")

    es_vid = _es_video(ruta_o_url)
    url_publica = _es_url_publica(ruta_o_url)
    tiene_archivo_local = bool(ruta_o_url) and not url_publica and os.path.exists(ruta_o_url)

    if es_vid:
        endpoint = f"https://graph-video.facebook.com/v21.0/{page_id}/videos"
        payload = {
            "access_token": access_token,
            "description": copy_texto or ""
        }
        if timestamp_programado:
            payload["published"] = "false"
            payload["scheduled_publish_time"] = str(timestamp_programado)

        if tiene_archivo_local:
            with open(ruta_o_url, "rb") as f_vid:
                resp = requests.post(endpoint, data=payload, files={"source": f_vid}, timeout=120)
        elif url_publica:
            payload["file_url"] = ruta_o_url.strip()
            resp = requests.post(endpoint, data=payload, timeout=120)
        else:
            raise ValueError("No se encontró un archivo de video válido o URL pública.")
    elif url_publica or tiene_archivo_local:
        endpoint = f"https://graph.facebook.com/v21.0/{page_id}/photos"
        payload = {
            "access_token": access_token,
            "caption": copy_texto or ""
        }
        if timestamp_programado:
            payload["published"] = "false"
            payload["scheduled_publish_time"] = str(timestamp_programado)

        if tiene_archivo_local:
            with open(ruta_o_url, "rb") as f_img:
                resp = requests.post(endpoint, data=payload, files={"source": f_img}, timeout=60)
        else:
            payload["url"] = ruta_o_url.strip()
            resp = requests.post(endpoint, data=payload, timeout=60)
    else:
        endpoint = f"https://graph.facebook.com/v21.0/{page_id}/feed"
        payload = {
            "access_token": access_token,
            "message": copy_texto or ""
        }
        if timestamp_programado:
            payload["published"] = "false"
            payload["scheduled_publish_time"] = str(timestamp_programado)
        resp = requests.post(endpoint, data=payload, timeout=60)

    data = resp.json()
    if resp.status_code >= 400 or "error" in data:
        err_msg = data.get("error", {}).get("message", str(data))
        raise RuntimeError(f"Error Graph API: {err_msg}")
    return data


def _ciclo_publicador_automatico():
    """Hilo en segundo plano: publica posts pendientes de TODOS los usuarios al llegar su fecha/hora."""
    while True:
        try:
            ahora = datetime.now()
            for uid in listar_todos_los_user_ids():
                db_disk = cargar_datos(user_id=uid)
                cal_nativo = db_disk.get("calendario_nativo", {})
                cfg_redes = db_disk.get("config_redes", {})
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
                    guardar_datos(db_disk, user_id=uid)
        except Exception:
            pass
        time.sleep(30)


@st.cache_resource
def _arrancar_hilo_publicador():
    hilo = threading.Thread(target=_ciclo_publicador_automatico, daemon=True)
    hilo.start()
    return hilo


def _normalizar_post(item: dict) -> dict:
    return {
        "ID": item.get("ID", uuid.uuid4().hex[:8]),
        "FECHA": str(item.get("FECHA", date.today().strftime("%Y-%m-%d"))),
        "TIPO": str(item.get("TIPO", "Imagen")),
        "COPY_FACEBOOK": str(item.get("COPY_FACEBOOK", "")),
        "HORARIO_FACEBOOK": str(item.get("HORARIO_FACEBOOK", "")),
        "COPY_INSTAGRAM": str(item.get("COPY_INSTAGRAM", "")),
        "HORARIO_INSTAGRAM": str(item.get("HORARIO_INSTAGRAM", "")),
        "URL_IMAGEN": str(item.get("URL_IMAGEN", "")),
        "ESTADO": str(item.get("ESTADO", "Pendiente")),
        "NOTA_API": str(item.get("NOTA_API", "")),
    }


def render():
    _arrancar_hilo_publicador()

    db = st.session_state.db
    marca = db["marca_activa"]
    carpeta_media = obtener_carpeta_media_usuario("media_calendario")

    st.subheader(f"📅 Parrilla de Contenidos y Publicación — {marca}")

    if "calendario_nativo" not in db:
        db["calendario_nativo"] = {}
    if marca not in db["calendario_nativo"]:
        db["calendario_nativo"][marca] = []

    if "config_redes" not in db:
        db["config_redes"] = {}
    if marca not in db["config_redes"]:
        db["config_redes"][marca] = {
            "page_id_fb": "",
            "fb_access_token": "",
            "auto_publicar_activo": False
        }

    posts_marca = [_normalizar_post(p) for p in db["calendario_nativo"][marca]]
    db["calendario_nativo"][marca] = posts_marca
    cred_marca = db["config_redes"][marca]

    # =========================================================================
    # 1. CONEXIÓN CON FACEBOOK PAGE (META GRAPH API)
    # =========================================================================
    with st.expander("🔗 Conexión Facebook Page (Publicación Directa y Automática)", expanded=False):
        st.caption("Configura el Page ID y Page Access Token de la página de Facebook correspondiente a esta marca.")
        c_p1, c_p2 = st.columns(2)
        page_id_in = c_p1.text_input("Facebook Page ID:", value=cred_marca.get("page_id_fb", ""), key=f"fb_pid_{marca}")
        token_fb_in = c_p2.text_input("Facebook Page Access Token:", value=cred_marca.get("fb_access_token", ""), type="password", key=f"fb_tok_{marca}")
        auto_pub_in = st.checkbox(
            "Activar publicación automática en segundo plano (revisa cada 30 seg.)",
            value=bool(cred_marca.get("auto_publicar_activo", False)),
            key=f"fb_auto_{marca}"
        )

        if st.button("💾 Guardar Credenciales de Facebook", type="primary", key=f"save_fb_{marca}"):
            cred_marca["page_id_fb"] = page_id_in.strip()
            cred_marca["fb_access_token"] = token_fb_in.strip()
            cred_marca["auto_publicar_activo"] = auto_pub_in
            guardar_datos(db)
            st.success("Credenciales de Facebook guardadas para esta marca.")

    # =========================================================================
    # 2. CARGA MASIVA EN LOTE (IMÁGENES / VIDEOS + EXCEL / CSV)
    # =========================================================================
    with st.expander("📦 Carga en Lote (Subir Imágenes/Videos y/o Importar Parrilla Excel/CSV)", expanded=False):
        col_l1, col_l2 = st.columns(2)

        with col_l1:
            st.markdown("**Subir archivos multimedia (Imágenes o Videos)**")
            archivos_subidos = st.file_uploader(
                "Selecciona uno o varios archivos:",
                type=["png", "jpg", "jpeg", "webp", "mp4", "mov", "avi", "webm"],
                accept_multiple_files=True,
                key=f"up_media_cal_{marca}"
            )
            fecha_lote = st.date_input("Fecha asignada al lote:", value=date.today(), key=f"fec_lote_{marca}")
            hora_lote = st.time_input("Hora base sugerida:", value=datetime.now().replace(second=0, microsecond=0).time(), key=f"hor_lote_{marca}")
            copy_base_lote = st.text_area("Copy base para los archivos subidos (opcional):", height=80, key=f"copy_lote_{marca}")

            if st.button("➕ Agregar Archivos a la Parrilla", type="primary", key=f"btn_add_lote_{marca}"):
                if archivos_subidos:
                    horario_str = f"{fecha_lote.strftime('%Y-%m-%d')} {hora_lote.strftime('%H:%M')}"
                    for f_up in archivos_subidos:
                        nombre_seguro = f"{uuid.uuid4().hex[:8]}_{f_up.name}"
                        ruta_guardada = os.path.join(carpeta_media, nombre_seguro)
                        with open(ruta_guardada, "wb") as out_f:
                            out_f.write(f_up.getbuffer())

                        tipo_m = "Video / Reel" if _es_video(ruta_guardada) else "Imagen"
                        posts_marca.append(_normalizar_post({
                            "FECHA": fecha_lote.strftime("%Y-%m-%d"),
                            "TIPO": tipo_m,
                            "COPY_FACEBOOK": copy_base_lote.strip(),
                            "HORARIO_FACEBOOK": horario_str,
                            "COPY_INSTAGRAM": copy_base_lote.strip(),
                            "HORARIO_INSTAGRAM": horario_str,
                            "URL_IMAGEN": ruta_guardada,
                            "ESTADO": "Pendiente"
                        }))
                    db["calendario_nativo"][marca] = posts_marca
                    guardar_datos(db)
                    st.success(f"Se agregaron {len(archivos_subidos)} archivo(s) a la parrilla.")
                    st.rerun()
                else:
                    st.warning("Selecciona al menos una imagen o video.")

        with col_l2:
            st.markdown("**Importar parrilla desde Excel (.xlsx) o CSV**")
            archivo_tabla = st.file_uploader(
                "Sube tu archivo de parrilla:",
                type=["xlsx", "csv"],
                key=f"up_tabla_cal_{marca}"
            )
            if archivo_tabla is not None and st.button("📥 Importar Filas a la Parrilla", key=f"btn_imp_tabla_{marca}"):
                try:
                    if archivo_tabla.name.lower().endswith(".csv"):
                        df_imp = pd.read_csv(archivo_tabla)
                    else:
                        df_imp = pd.read_excel(archivo_tabla)

                    agregados = 0
                    for _, row in df_imp.iterrows():
                        copy_fb = str(row.get("COPY_FACEBOOK", row.get("Copy", "")) or "")
                        copy_ig = str(row.get("COPY_INSTAGRAM", copy_fb) or "")
                        url_img = str(row.get("URL_IMAGEN", row.get("Imagen", "")) or "")
                        if copy_fb.strip() or copy_ig.strip() or url_img.strip():
                            posts_marca.append(_normalizar_post({
                                "FECHA": str(row.get("FECHA", date.today().strftime("%Y-%m-%d"))),
                                "TIPO": str(row.get("TIPO", "Video / Reel" if _es_video(url_img) else "Imagen")),
                                "COPY_FACEBOOK": copy_fb,
                                "HORARIO_FACEBOOK": str(row.get("HORARIO_FACEBOOK", "")),
                                "COPY_INSTAGRAM": copy_ig,
                                "HORARIO_INSTAGRAM": str(row.get("HORARIO_INSTAGRAM", "")),
                                "URL_IMAGEN": url_img,
                                "ESTADO": str(row.get("ESTADO", "Pendiente"))
                            }))
                            agregados += 1

                    db["calendario_nativo"][marca] = posts_marca
                    guardar_datos(db)
                    st.success(f"Se importaron {agregados} publicaciones.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al importar archivo: {str(e)}")

    # =========================================================================
    # 3. CREAR PUBLICACIÓN INDIVIDUAL
    # =========================================================================
    with st.expander("✍️ Nueva Publicación Individual", expanded=not bool(posts_marca)):
        n_c1, n_c2, n_c3 = st.columns(3)
        fecha_n = n_c1.date_input("Fecha de publicación:", value=date.today(), key=f"fec_n_{marca}")
        tipo_n = n_c2.selectbox("Formato:", ["Imagen", "Video / Reel", "Carrusel / Texto"], key=f"tipo_n_{marca}")
        estado_n = n_c3.selectbox("Estado inicial:", ["Pendiente", "Borrador", "Publicado"], key=f"est_n_{marca}")

        h_c1, h_c2 = st.columns(2)
        hor_fb_n = h_c1.text_input("Horario Facebook (YYYY-MM-DD HH:MM):", value=f"{fecha_n.strftime('%Y-%m-%d')} 12:00", key=f"hfb_n_{marca}")
        hor_ig_n = h_c2.text_input("Horario Instagram (YYYY-MM-DD HH:MM):", value=f"{fecha_n.strftime('%Y-%m-%d')} 12:30", key=f"hig_n_{marca}")

        cp_c1, cp_c2 = st.columns(2)
        copy_fb_n = cp_c1.text_area("Copy Facebook:", height=110, key=f"cfb_n_{marca}")
        copy_ig_n = cp_c2.text_area("Copy Instagram:", height=110, key=f"cig_n_{marca}")

        m_c1, m_c2 = st.columns(2)
        url_img_n = m_c1.text_input("URL pública de imagen o video (opcional):", key=f"url_n_{marca}")
        archivo_n = m_c2.file_uploader("O subir archivo local (imagen/video):", type=["png", "jpg", "jpeg", "webp", "mp4", "mov", "webm"], key=f"file_n_{marca}")

        if st.button("💾 Guardar Publicación", type="primary", key=f"btn_save_post_{marca}"):
            media_final = url_img_n.strip()
            if archivo_n is not None:
                nombre_s = f"{uuid.uuid4().hex[:8]}_{archivo_n.name}"
                ruta_s = os.path.join(carpeta_media, nombre_s)
                with open(ruta_s, "wb") as f_out:
                    f_out.write(archivo_n.getbuffer())
                media_final = ruta_s

            posts_marca.append(_normalizar_post({
                "FECHA": fecha_n.strftime("%Y-%m-%d"),
                "TIPO": tipo_n,
                "COPY_FACEBOOK": copy_fb_n,
                "HORARIO_FACEBOOK": hor_fb_n,
                "COPY_INSTAGRAM": copy_ig_n,
                "HORARIO_INSTAGRAM": hor_ig_n,
                "URL_IMAGEN": media_final,
                "ESTADO": estado_n
            }))
            db["calendario_nativo"][marca] = posts_marca
            guardar_datos(db)
            st.success("Publicación guardada en la parrilla.")
            st.rerun()

    # =========================================================================
    # 4. TABLERO Y ACCIONES POR PUBLICACIÓN
    # =========================================================================
    st.markdown("---")
    st.markdown("### 📋 Parrilla Programada")

    if not posts_marca:
        st.info("Aún no hay publicaciones registradas para esta marca.")
        return

    df_vista = pd.DataFrame(posts_marca)
    st.dataframe(
        df_vista[["FECHA", "TIPO", "HORARIO_FACEBOOK", "HORARIO_INSTAGRAM", "ESTADO", "COPY_FACEBOOK"]],
        width="stretch"
    )

    excel_buf = pd.ExcelWriter("temp_parrilla.xlsx", engine="openpyxl")
    df_vista.to_excel(excel_buf, index=False, sheet_name="Parrilla")
    excel_buf.close()
    with open("temp_parrilla.xlsx", "rb") as f_ex:
        st.download_button(
            "📥 Exportar Parrilla a Excel (.xlsx)",
            data=f_ex.read(),
            file_name=f"Parrilla_{marca.replace(' ', '_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    try:
        os.remove("temp_parrilla.xlsx")
    except Exception:
        pass

    st.markdown("#### 🎯 Gestionar y Publicar Elementos")
    for idx, post in enumerate(posts_marca):
        with st.container(border=True):
            c_prev, c_info, c_acc = st.columns([1.4, 3.2, 1.8])

            with c_prev:
                media_ref = post.get("URL_IMAGEN", "")
                if media_ref and _es_video(media_ref):
                    if _es_url_publica(media_ref) or os.path.exists(media_ref):
                        st.video(media_ref)
                elif media_ref and (_es_url_publica(media_ref) or os.path.exists(media_ref)):
                    st.image(media_ref, width="stretch")
                else:
                    st.caption("Sin multimedia")

            with c_info:
                st.markdown(f"**{post['FECHA']}** • `{post['TIPO']}` • Estado: **{post['ESTADO']}**")
                st.caption(f"FB: `{post['HORARIO_FACEBOOK']}` | IG: `{post['HORARIO_INSTAGRAM']}`")
                st.write(post.get("COPY_FACEBOOK") or post.get("COPY_INSTAGRAM") or "(Sin copy)")
                if post.get("NOTA_API"):
                    st.caption(f"ℹ️ {post['NOTA_API']}")

            with c_acc:
                if st.button("🚀 Publicar FB Ahora", key=f"pub_now_{marca}_{post['ID']}", width="stretch"):
                    try:
                        res_fb = _publicar_en_facebook(
                            page_id=cred_marca.get("page_id_fb", ""),
                            access_token=cred_marca.get("fb_access_token", ""),
                            copy_texto=post.get("COPY_FACEBOOK", "") or post.get("COPY_INSTAGRAM", ""),
                            ruta_o_url=post.get("URL_IMAGEN", ""),
                            timestamp_programado=None
                        )
                        post["ESTADO"] = "Publicado"
                        post["NOTA_API"] = f"ID: {res_fb.get('id', res_fb.get('post_id', 'OK'))}"
                        guardar_datos(db)
                        st.success("Publicado en Facebook.")
                        st.rerun()
                    except Exception as e:
                        post["ESTADO"] = "Error API"
                        post["NOTA_API"] = str(e)
                        guardar_datos(db)
                        st.error(str(e))

                nuevo_est = st.selectbox(
                    "Cambiar estado:",
                    ["Pendiente", "Borrador", "Publicado", "Error API"],
                    index=["Pendiente", "Borrador", "Publicado", "Error API"].index(post["ESTADO"]) if post["ESTADO"] in ["Pendiente", "Borrador", "Publicado", "Error API"] else 0,
                    key=f"sel_est_{marca}_{post['ID']}",
                    label_visibility="collapsed"
                )
                if nuevo_est != post["ESTADO"]:
                    post["ESTADO"] = nuevo_est
                    guardar_datos(db)
                    st.rerun()

                if st.button("🗑️ Eliminar", key=f"del_post_{marca}_{post['ID']}", width="stretch"):
                    posts_marca.pop(idx)
                    db["calendario_nativo"][marca] = posts_marca
                    guardar_datos(db)
                    st.rerun()