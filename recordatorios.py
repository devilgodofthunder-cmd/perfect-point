# recordatorios.py
import os
import re
import time
import uuid
import smtplib
import threading
from email.message import EmailMessage
from datetime import datetime, date, timedelta
import streamlit as st
from storage import (
    cargar_datos,
    guardar_datos,
    listar_todos_los_user_ids,
    obtener_carpeta_media_usuario,
)

TIPOS_ADJUNTO = [
    "pdf", "png", "jpg", "jpeg", "webp",
    "xlsx", "xls", "csv",
    "docx", "doc", "pptx", "txt",
    "mp4", "mov", "zip"
]


def _emails_validos(cadena_correos: str) -> list[str]:
    if not cadena_correos:
        return []
    partes = [c.strip() for c in str(cadena_correos).split(",") if c.strip()]
    return [c for c in partes if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", c)]


def enviar_correo_alerta(remitente: str, password_app: str, destinatarios: list[str], asunto: str, cuerpo_html: str, rutas_adjuntos: list[str] | None = None):
    if not remitente or not password_app or not destinatarios:
        raise ValueError("Faltan credenciales SMTP o destinatarios.")

    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = remitente
    msg["To"] = ", ".join(destinatarios)
    msg.set_content("Tienes un nuevo recordatorio programado desde tu Plataforma Integral de Marketing.")
    msg.add_alternative(cuerpo_html, subtype="html")

    if rutas_adjuntos:
        for ruta in rutas_adjuntos:
            if ruta and os.path.exists(ruta):
                nombre_limpio = os.path.basename(ruta).split("_", 1)[-1]
                with open(ruta, "rb") as f:
                    data = f.read()
                msg.add_attachment(
                    data,
                    maintype="application",
                    subtype="octet-stream",
                    filename=nombre_limpio
                )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as smtp:
        smtp.login(remitente, password_app)
        smtp.send_message(msg)


def _ciclo_segundo_plano():
    """Revisa periódicamente los recordatorios pendientes de TODOS los usuarios registrados."""
    while True:
        try:
            ahora = datetime.now()
            user_ids = listar_todos_los_user_ids()

            for uid in user_ids:
                db_u = cargar_datos(user_id=uid)
                cfg = db_u.get("config_alertas", {})
                lista = db_u.get("recordatorios", [])
                if not lista:
                    continue

                remitente = cfg.get("remitente", "")
                password = cfg.get("password_app", "")
                dest_def = cfg.get("destinatarios_default", "")
                hubo_cambios = False

                for r in lista:
                    if r.get("enviado"):
                        continue
                    try:
                        dt_prog = datetime.strptime(f"{r['fecha']} {r['hora']}", "%Y-%m-%d %H:%M")
                    except Exception:
                        continue

                    if ahora >= dt_prog:
                        dests = _emails_validos(r.get("destinatarios") or dest_def)
                        if remitente and password and dests:
                            cuerpo = f"""
                            <div style="font-family:Segoe UI,Arial,sans-serif;padding:20px;border:1px solid #cbd5e1;border-radius:12px;max-width:600px;">
                                <h2 style="color:#0f766e;margin-top:0;">⏰ Recordatorio: {r.get('titulo', '')}</h2>
                                <p><strong>Marca:</strong> {r.get('marca', 'General')}</p>
                                <p><strong>Programado para:</strong> {r.get('fecha', '')} a las {r.get('hora', '')}</p>
                                <div style="background:#f8fafc;padding:12px;border-radius:8px;color:#1e293b;">
                                    {r.get('mensaje', '')}
                                </div>
                            </div>
                            """
                            try:
                                enviar_correo_alerta(
                                    remitente=remitente,
                                    password_app=password,
                                    destinatarios=dests,
                                    asunto=f"⏰ Recordatorio [{r.get('marca', 'MKT')}]: {r.get('titulo', '')}",
                                    cuerpo_html=cuerpo,
                                    rutas_adjuntos=r.get("adjuntos", [])
                                )
                                r["enviado"] = True
                                r["estado_envio"] = f"Enviado {ahora.strftime('%d/%m %H:%M')}"
                            except Exception as e:
                                r["estado_envio"] = f"Error: {str(e)[:60]}"
                            hubo_cambios = True

                if hubo_cambios:
                    guardar_datos(db_u, user_id=uid)
        except Exception:
            pass
        time.sleep(30)


@st.cache_resource
def iniciar_motor_recordatorios():
    hilo = threading.Thread(target=_ciclo_segundo_plano, daemon=True)
    hilo.start()
    return hilo


def render_panel_recordatorios(db):
    """Panel lateral de alertas y recordatorios con adjuntos privados por usuario."""
    cfg = db.setdefault("config_alertas", {
        "remitente": "",
        "password_app": "",
        "destinatarios_default": ""
    })
    recordatorios = db.setdefault("recordatorios", [])
    marca_activa = db.get("marca_activa", "General")
    carpeta_adj = obtener_carpeta_media_usuario("adjuntos_recordatorios")

    pendientes = [r for r in recordatorios if not r.get("enviado")]
    etiqueta_exp = f"⏰ Alertas y Recordatorios ({len(pendientes)})" if pendientes else "⏰ Alertas y Recordatorios"

    with st.expander(etiqueta_exp, expanded=False):
        with st.popover("⚙️ Configurar Correo Emisor (Gmail)", width="stretch"):
            st.caption("Usa una **Contraseña de Aplicación** de Google (16 caracteres).")
            rem_in = st.text_input("Correo Gmail remitente:", value=cfg.get("remitente", ""), key="rec_rem")
            pwd_in = st.text_input("Contraseña de Aplicación:", value=cfg.get("password_app", ""), type="password", key="rec_pwd")
            des_in = st.text_input("Destinatario(s) por defecto:", value=cfg.get("destinatarios_default", ""), placeholder="correo1@dom.com, correo2@dom.com", key="rec_des")
            if st.button("💾 Guardar Config Correo", type="primary", width="stretch", key="rec_save_cfg"):
                cfg["remitente"] = rem_in.strip()
                cfg["password_app"] = pwd_in.strip()
                cfg["destinatarios_default"] = des_in.strip()
                guardar_datos(db)
                st.success("Configuración guardada.")

        tit_r = st.text_input("Título de la alerta:", placeholder="Ej. Revisar presupuesto semanal", key="rec_tit")
        c_f, c_h = st.columns(2)
        fec_r = c_f.date_input("Fecha:", value=date.today(), key="rec_fec")
        hor_r = c_h.time_input("Hora:", value=(datetime.now() + timedelta(minutes=15)).time(), key="rec_hor")
        msg_r = st.text_area("Mensaje / Detalle:", height=65, placeholder="Notas o instrucciones...", key="rec_msg")
        dest_r = st.text_input("Enviar a (opcional, usa defecto):", placeholder="otro@correo.com", key="rec_dest_custom")

        archivos_r = st.file_uploader(
            "Adjuntar archivos (opcional):",
            type=TIPOS_ADJUNTO,
            accept_multiple_files=True,
            key="rec_files"
        )

        if st.button("➕ Programar Recordatorio", type="primary", width="stretch", key="rec_add"):
            if not tit_r.strip():
                st.warning("Escribe un título para el recordatorio.")
            else:
                rutas_guardadas = []
                if archivos_r:
                    for f_up in archivos_r:
                        nom_u = f"{uuid.uuid4().hex[:8]}_{f_up.name}"
                        ruta_f = os.path.join(carpeta_adj, nom_u)
                        with open(ruta_f, "wb") as f_out:
                            f_out.write(f_up.getbuffer())
                        rutas_guardadas.append(ruta_f)

                recordatorios.append({
                    "id": uuid.uuid4().hex[:8],
                    "marca": marca_activa,
                    "titulo": tit_r.strip(),
                    "fecha": fec_r.strftime("%Y-%m-%d"),
                    "hora": hor_r.strftime("%H:%M"),
                    "mensaje": msg_r.strip(),
                    "destinatarios": dest_r.strip(),
                    "adjuntos": rutas_guardadas,
                    "enviado": False,
                    "estado_envio": "Pendiente"
                })
                guardar_datos(db)
                st.success("Alerta programada.")
                st.rerun()

        if recordatorios:
            st.markdown("---")
            for idx, r in enumerate(reversed(recordatorios[-6:])):
                icono = "✅" if r.get("enviado") else "⏳"
                c1, c2 = st.columns([4, 1])
                c1.caption(f"{icono} **{r['titulo']}**\n📅 {r['fecha']} {r['hora']} ({r.get('marca', '')})")
                if c2.button("🗑️", key=f"del_rec_{r['id']}"):
                    for adj_p in r.get("adjuntos", []):
                        if adj_p and os.path.exists(adj_p):
                            try:
                                os.remove(adj_p)
                            except Exception:
                                pass
                    db["recordatorios"] = [x for x in db["recordatorios"] if x["id"] != r["id"]]
                    guardar_datos(db)
                    st.rerun()