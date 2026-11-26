# recordatorios.py
import os
import time
import uuid
import urllib.parse
import threading
import smtplib
from datetime import datetime, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import requests
import streamlit as st
from storage import cargar_datos, guardar_datos

CARPETA_ADJUNTOS = "adjuntos_recordatorios"
os.makedirs(CARPETA_ADJUNTOS, exist_ok=True)


def _enviar_correo(destinatario, remitente, password_app, asunto, mensaje, ruta_imagen=None):
    """Envía el recordatorio por correo electrónico con imagen adjunta opcional."""
    msg = MIMEMultipart()
    msg["From"] = remitente
    msg["To"] = destinatario
    msg["Subject"] = asunto

    msg.attach(MIMEText(mensaje, "plain", "utf-8"))

    if ruta_imagen and os.path.exists(ruta_imagen):
        with open(ruta_imagen, "rb") as f:
            img_data = f.read()
        nombre_img = os.path.basename(ruta_imagen)
        imagen_adjunta = MIMEImage(img_data, name=nombre_img)
        msg.attach(imagen_adjunta)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(remitente, password_app)
        server.send_message(msg)


def _enviar_whatsapp_greenapi(api_url, id_instance, api_token, telefono, mensaje, ruta_imagen=None):
    """Envía mensaje de texto o imagen con descripción a WhatsApp mediante Green-API."""
    base_url = api_url.rstrip("/")
    chat_id = f"{telefono.strip()}@c.us"

    if ruta_imagen and os.path.exists(ruta_imagen):
        url = f"{base_url}/waInstance{id_instance}/sendFileByUpload/{api_token}"
        nombre_archivo = os.path.basename(ruta_imagen)
        with open(ruta_imagen, "rb") as f:
            resp = requests.post(
                url,
                data={"chatId": chat_id, "caption": mensaje},
                files={"file": (nombre_archivo, f, "image/jpeg")},
                timeout=20
            )
    else:
        url = f"{base_url}/waInstance{id_instance}/sendMessage/{api_token}"
        resp = requests.post(
            url,
            json={"chatId": chat_id, "message": mensaje},
            timeout=15
        )

    resp.raise_for_status()
    data = resp.json()
    if "idMessage" not in data:
        raise RuntimeError(f"Respuesta inesperada de Green-API: {data}")


def _procesar_recordatorio(rec, config_notif):
    """Ejecuta el envío según los canales elegidos en el recordatorio."""
    errores = []
    marca = rec.get("marca", "General")
    asunto = f"⏰ Recordatorio Marketing ({marca})"
    cuerpo = (
        f"⏰ *Recordatorio — {marca}*\n"
        f"📅 Programado: {rec['fecha_hora']}\n\n"
        f"{rec['mensaje']}"
    )

    if rec.get("por_correo"):
        remitente = config_notif.get("correo_remitente", "")
        pass_app = config_notif.get("correo_password", "")
        destino = config_notif.get("correo_destino", "") or remitente
        if remitente and pass_app and destino:
            try:
                _enviar_correo(
                    destinatario=destino,
                    remitente=remitente,
                    password_app=pass_app,
                    asunto=asunto,
                    mensaje=cuerpo,
                    ruta_imagen=rec.get("ruta_imagen")
                )
            except Exception as e:
                errores.append(f"Correo: {e}")
        else:
            errores.append("Falta configurar Correo/Contraseña")

    if rec.get("por_whatsapp"):
        api_url = config_notif.get("ga_api_url", "")
        id_inst = config_notif.get("ga_id_instance", "")
        api_tok = config_notif.get("ga_api_token", "")
        tel = config_notif.get("whats_telefono", "")
        if api_url and id_inst and api_tok and tel:
            try:
                _enviar_whatsapp_greenapi(
                    api_url=api_url,
                    id_instance=id_inst,
                    api_token=api_tok,
                    telefono=tel,
                    mensaje=cuerpo,
                    ruta_imagen=rec.get("ruta_imagen")
                )
            except Exception as e:
                errores.append(f"WhatsApp: {e}")
        else:
            errores.append("Falta configurar datos de Green-API")

    return errores


def _ciclo_segundo_plano():
    """Hilo silencioso que verifica cada 15 segundos si hay recordatorios por vencer."""
    while True:
        try:
            db_disk = cargar_datos()
            lista = db_disk.get("recordatorios", [])
            config = db_disk.get("config_notificaciones", {})
            ahora = datetime.now()
            hubo_cambios = False

            for rec in lista:
                if not rec.get("enviado", False):
                    dt_prog = datetime.strptime(rec["fecha_hora"], "%Y-%m-%d %H:%M")
                    if ahora >= dt_prog:
                        errores = _procesar_recordatorio(rec, config)
                        rec["enviado"] = True
                        rec["estado"] = "Enviado ✅" if not errores else f"Error ⚠️ ({'; '.join(errores)})"
                        hubo_cambios = True

            if hubo_cambios:
                guardar_datos(db_disk)
        except Exception:
            pass
        time.sleep(15)


@st.cache_resource
def iniciar_motor_recordatorios():
    """Inicia una única instancia del reloj en segundo plano."""
    hilo = threading.Thread(target=_ciclo_segundo_plano, daemon=True)
    hilo.start()
    return hilo


def render_panel_derecho():
    """Dibuja el módulo de recordatorios en la columna derecha de la pantalla principal."""
    iniciar_motor_recordatorios()

    db_actualizado = cargar_datos()
    st.session_state.db["recordatorios"] = db_actualizado.get("recordatorios", [])
    if "config_notificaciones" not in st.session_state.db:
        st.session_state.db["config_notificaciones"] = db_actualizado.get("config_notificaciones", {})

    db = st.session_state.db
    marca_activa = db.get("marca_activa", "General")
    config = db["config_notificaciones"]

    st.markdown("### ⏰ Recordatorios")
    st.caption(f"Marca: **{marca_activa}**")

    # --- FORMULARIO PARA CREAR RECORDATORIO ---
    with st.container(border=True):
        mensaje = st.text_area(
            "Mensaje del recordatorio:",
            height=90,
            placeholder="Ej. Subir reel de promoción o revisar pauta de fin de semana...",
            key="rec_mensaje_input"
        )

        img_ref = st.file_uploader(
            "Imagen de referencia (opcional):",
            type=["png", "jpg", "jpeg"],
            key="rec_img_input"
        )

        c_fecha, c_hora = st.columns(2)
        fecha_sel = c_fecha.date_input("Día:", value=date.today(), key="rec_fecha_input")
        hora_sel = c_hora.time_input("Hora:", key="rec_hora_input")

        st.write("**¿Por dónde avisarte?**")
        c_chk1, c_chk2 = st.columns(2)
        enviar_whats = c_chk1.checkbox("WhatsApp", value=True, key="rec_chk_wa")
        enviar_mail = c_chk2.checkbox("Correo", value=False, key="rec_chk_mail")

        if st.button("🔔 Programar Recordatorio", type="primary", width="stretch"):
            if not mensaje.strip():
                st.warning("Escribe el mensaje del recordatorio.")
            elif not enviar_whats and not enviar_mail:
                st.warning("Selecciona al menos un medio (WhatsApp o Correo).")
            else:
                ruta_guardada = None
                if img_ref is not None:
                    ext = os.path.splitext(img_ref.name)[1]
                    nombre_unico = f"{uuid.uuid4().hex}{ext}"
                    ruta_guardada = os.path.join(CARPETA_ADJUNTOS, nombre_unico)
                    with open(ruta_guardada, "wb") as f:
                        f.write(img_ref.getbuffer())

                fecha_hora_str = f"{fecha_sel.strftime('%Y-%m-%d')} {hora_sel.strftime('%H:%M')}"

                nuevo_rec = {
                    "id": uuid.uuid4().hex[:8],
                    "marca": marca_activa,
                    "mensaje": mensaje.strip(),
                    "fecha_hora": fecha_hora_str,
                    "por_whatsapp": enviar_whats,
                    "por_correo": enviar_mail,
                    "ruta_imagen": ruta_guardada,
                    "enviado": False,
                    "estado": "Pendiente ⏳"
                }

                db.setdefault("recordatorios", []).append(nuevo_rec)
                guardar_datos(db)
                st.success(f"Programado para {fecha_hora_str}")
                st.rerun()

    # --- CONFIGURACIÓN DE CREDENCIALES DE ENVÍO ---
    with st.expander("⚙️ Configurar WhatsApp / Correo"):
        st.caption("**1. WhatsApp Automático (Green-API)**")
        ga_url = st.text_input(
            "apiUrl:",
            value=config.get("ga_api_url", "https://7107.api.greenapi.com"),
            placeholder="https://7107.api.greenapi.com"
        )
        ga_id = st.text_input(
            "idInstance:",
            value=config.get("ga_id_instance", ""),
            placeholder="Ej. 710722805509"
        )
        ga_tok = st.text_input(
            "apiTokenInstance:",
            value=config.get("ga_api_token", ""),
            type="password"
        )
        wa_tel = st.text_input(
            "Tu número con lada (ej. 5215612472263):",
            value=config.get("whats_telefono", "")
        )

        st.markdown("---")
        st.caption("**2. Correo (Gmail SMTP)**")
        mail_rem = st.text_input(
            "Tu Gmail:",
            value=config.get("correo_remitente", ""),
            placeholder="tucorreo@gmail.com"
        )
        mail_pass = st.text_input(
            "Contraseña de aplicación (16 letras):",
            value=config.get("correo_password", ""),
            type="password"
        )
        mail_dest = st.text_input(
            "Correo destino (opcional si es el mismo):",
            value=config.get("correo_destino", ""),
            placeholder="destino@correo.com"
        )

        if st.button("💾 Guardar Configuración", width="stretch"):
            db["config_notificaciones"] = {
                "ga_api_url": ga_url.strip(),
                "ga_id_instance": ga_id.strip(),
                "ga_api_token": ga_tok.strip(),
                "whats_telefono": wa_tel.strip(),
                "correo_remitente": mail_rem.strip(),
                "correo_password": mail_pass.strip(),
                "correo_destino": mail_dest.strip()
            }
            guardar_datos(db)
            st.success("Configuración guardada.")

    # --- LISTA DE RECORDATORIOS ---
    st.markdown("---")
    st.markdown("**📋 Agenda de Recordatorios**")
    recordatorios = db.get("recordatorios", [])

    if not recordatorios:
        st.caption("No tienes recordatorios programados.")
    else:
        for i, rec in enumerate(reversed(recordatorios)):
            idx_real = len(recordatorios) - 1 - i
            with st.container(border=True):
                st.caption(f"📅 **{rec['fecha_hora']}** | 🏢 {rec['marca']}")
                st.write(rec["mensaje"])
                if rec.get("ruta_imagen"):
                    st.caption("🖼️ Con imagen adjunta")
                
                medios = []
                if rec.get("por_whatsapp"):
                    medios.append("WhatsApp")
                if rec.get("por_correo"):
                    medios.append("Correo")
                
                st.caption(f"Vía: {' + '.join(medios)} • **{rec.get('estado', 'Pendiente')}**")

                b1, b2 = st.columns(2)
                texto_wa = urllib.parse.quote(f"Recordatorio ({rec['marca']}): {rec['mensaje']}")
                b1.link_button("📲 Abrir WA", f"https://wa.me/?text={texto_wa}", width="stretch")
                
                if b2.button("🗑️ Borrar", key=f"del_rec_{rec['id']}", width="stretch"):
                    if rec.get("ruta_imagen") and os.path.exists(rec["ruta_imagen"]):
                        try:
                            os.remove(rec["ruta_imagen"])
                        except Exception:
                            pass
                    db["recordatorios"].pop(idx_real)
                    guardar_datos(db)
                    st.rerun()