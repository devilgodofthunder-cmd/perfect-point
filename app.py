# app.py
import re
import streamlit as st
from storage import (
    cargar_datos,
    guardar_datos,
    autenticar_o_registrar_usuario,
    verificar_estado_suscripcion,
    cargar_registro_cuentas,
    actualizar_suscripcion_usuario,
    obtener_admin_emails,
)
from recordatorios import iniciar_motor_recordatorios, render_panel_recordatorios
from modulos import modulo1, modulo2, modulo3, modulo4, modulo5, modulo6

st.set_page_config(
    page_title="Plataforma Integral de Marketing",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Arrancar motor de alertas en segundo plano (multi-usuario)
iniciar_motor_recordatorios()


def _email_valido(correo: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", str(correo).strip()))


def _render_pantalla_acceso():
    st.markdown("""
    <style>
        .login-hero {
            max-width: 560px;
            margin: 30px auto 18px auto;
            background: linear-gradient(135deg, #0F172A 0%, #1E293B 60%, #0F766E 100%);
            padding: 28px 32px;
            border-radius: 18px;
            border: 1px solid #334155;
            color: #F8FAFC;
            text-align: center;
        }
        .login-hero h1 { margin: 0; font-size: 26px; }
        .login-hero p { margin: 8px 0 0 0; color: #CBD5E1; font-size: 14px; }
    </style>
    <div class="login-hero">
        <h1>🚀 Plataforma Integral de Marketing</h1>
        <p>Presupuestos • Generador IA • Parrillas Meta Ads • Eventos • Analítica &amp; Almacén Creativo</p>
    </div>
    """, unsafe_allow_html=True)

    _, col_centro, _ = st.columns([1, 1.4, 1])
    with col_centro:
        with st.container(border=True):
            st.subheader("🔐 Iniciar Sesión o Activar Demo Gratuita")
            st.caption("Ingresa tu usuario y correo electrónico. Si es tu primera vez, obtendrás **3 días de prueba gratuita** con acceso completo.")

            with st.form("form_login_saas"):
                nombre_in = st.text_input("Nombre de Usuario o Agencia:", placeholder="Ej. Luis González / Point Grid")
                email_in = st.text_input("Correo Electrónico:", placeholder="tucorreo@empresa.com")
                submit_btn = st.form_submit_button("Ingresar a la Plataforma", type="primary", width="stretch")

                if submit_btn:
                    if not nombre_in.strip():
                        st.error("Por favor escribe tu nombre de usuario.")
                    elif not _email_valido(email_in):
                        st.error("Ingresa un correo electrónico válido.")
                    else:
                        estado = autenticar_o_registrar_usuario(nombre_in.strip(), email_in.strip())
                        info = estado["info"]
                        st.session_state["auth_user_id"] = info["user_id"]
                        st.session_state["auth_user_key"] = info["email"]
                        st.session_state["auth_user_name"] = info["nombre"]
                        st.session_state["auth_user_email"] = info["email"]
                        if "db" in st.session_state:
                            del st.session_state["db"]
                        st.rerun()


def _render_pantalla_bloqueo(estado_sub: dict):
    info = estado_sub.get("info", {})
    _, col_c, _ = st.columns([1, 1.6, 1])
    with col_c:
        with st.container(border=True):
            st.error("🔒 Tu periodo de prueba gratuita (Demo) o suscripción ha finalizado.")
            st.markdown(f"""
            Hola **{info.get('nombre', 'Usuario')}** (`{info.get('email', '')}`):

            Tu tiempo de prueba gratuita ha concluido y el acceso a los módulos se encuentra pausado temporalmente hasta confirmar la activación de tu plan.

            ### 💳 ¿Cómo reactivar tu cuenta inmediatamente?
            1. Realiza el pago de tu suscripción mensual o anual.
            2. Envía tu comprobante junto con tu correo registrado (**`{info.get('email', '')}`**) por WhatsApp o correo electrónico.
            3. En cuanto se confirme el cobro, tu acceso quedará habilitado con toda tu información intacta.
            """)

            c1, c2 = st.columns(2)
            c1.link_button("📲 Enviar Comprobante por WhatsApp", "https://wa.me/525667462837", width="stretch")
            if c2.button("🔄 Ya pagué, verificar acceso", type="primary", width="stretch"):
                st.rerun()

            st.markdown("---")
            if st.button("🚪 Cerrar sesión / Cambiar cuenta", width="stretch"):
                for k in ["auth_user_id", "auth_user_key", "auth_user_name", "auth_user_email", "db"]:
                    st.session_state.pop(k, None)
                st.rerun()


# -----------------------------------------------------------------------------
# CONTROL DE ACCESO Y SESIÓN
# -----------------------------------------------------------------------------
if "auth_user_id" not in st.session_state:
    _render_pantalla_acceso()
    st.stop()

estado_suscripcion = verificar_estado_suscripcion(st.session_state["auth_user_id"])
if not estado_suscripcion["acceso_permitido"]:
    _render_pantalla_bloqueo(estado_suscripcion)
    st.stop()

# Cargar base de datos aislada del usuario autenticado
if "db" not in st.session_state:
    st.session_state.db = cargar_datos(st.session_state["auth_user_id"])

db = st.session_state.db
info_usuario = estado_suscripcion["info"]
es_admin = info_usuario.get("email", "").lower() in obtener_admin_emails() or info_usuario.get("plan") == "admin"

# Compatibilidad si viene de un respaldo o enlace directo de evento
try:
    q_params = st.query_params
    if "evento_req" in q_params:
        modulo4.render_portal_externo()
        st.stop()
except Exception:
    pass

# =============================================================================
# BARRA LATERAL: PERFIL, PLAN, ALERTAS, MARCAS Y NAVEGACIÓN
# =============================================================================
with st.sidebar:
    st.title("🚀 Marketing Hub")
    st.caption(f"👤 **{info_usuario.get('nombre', '')}**\n📧 `{info_usuario.get('email', '')}`")

    if es_admin:
        st.success("👑 Cuenta Administradora")
    elif info_usuario.get("plan") == "demo":
        dias_r = estado_suscripcion["dias_restantes"]
        st.warning(f"⏳ **Modo Demo:** Te quedan **{dias_r} día(s)** de prueba.")
    else:
        dias_r = estado_suscripcion["dias_restantes"]
        st.info(f"✅ **Plan Activo:** {dias_r} día(s) vigentes.")

    if st.button("🚪 Cerrar Sesión", width="stretch"):
        for k in ["auth_user_id", "auth_user_key", "auth_user_name", "auth_user_email", "db"]:
            st.session_state.pop(k, None)
        st.rerun()

    st.markdown("---")

    # Panel de Recordatorios y Alertas por correo aislado por usuario
    render_panel_recordatorios(db)

    st.markdown("---")

    # Selector de Marca Activa
    st.markdown("### 🏢 Marca Activa")
    lista_marcas = list(db.get("marcas", {}).keys())
    if not lista_marcas:
        db["marcas"] = {"Mi Marca": {"grupo": "General", "enlace": ""}}
        lista_marcas = ["Mi Marca"]

    marca_actual = db.get("marca_activa", lista_marcas[0])
    if marca_actual not in lista_marcas:
        marca_actual = lista_marcas[0]
        db["marca_activa"] = marca_actual

    marca_sel = st.selectbox(
        "Trabajando con:",
        lista_marcas,
        index=lista_marcas.index(marca_actual),
        label_visibility="collapsed"
    )
    if marca_sel != db["marca_activa"]:
        db["marca_activa"] = marca_sel
        guardar_datos(db)
        st.rerun()

    with st.expander("➕ Agregar o Gestionar Marcas"):
        nueva_m = st.text_input("Nombre de la nueva marca:", placeholder="Ej. Punto Verde MX")
        nuevo_g = st.text_input("Giro / Grupo:", placeholder="Ej. Automotriz / Restaurante")
        if st.button("Agregar Marca", width="stretch"):
            if nueva_m.strip() and nueva_m.strip() not in db["marcas"]:
                db["marcas"][nueva_m.strip()] = {"grupo": nuevo_g.strip() or "General", "enlace": ""}
                db["marca_activa"] = nueva_m.strip()
                guardar_datos(db)
                st.rerun()

        if len(lista_marcas) > 1:
            m_borrar = st.selectbox("Eliminar marca:", ["Seleccionar..."] + lista_marcas)
            if m_borrar != "Seleccionar..." and st.button("🗑️ Eliminar Marca Seleccionada", width="stretch"):
                del db["marcas"][m_borrar]
                db["marca_activa"] = list(db["marcas"].keys())[0]
                guardar_datos(db)
                st.rerun()

    st.markdown("---")

    # Menú Principal de Módulos
    opciones_menu = [
        "1️⃣ Presupuesto y Gastos",
        "2️⃣ Generador de Contenido IA",
        "3️⃣ Parrilla y Publicación",
        "4️⃣ Eventos y Briefs",
        "5️⃣ Resultados y Analítica",
        "6️⃣ Almacén Creativo & PDF"
    ]
    if es_admin:
        opciones_menu.append("👑 Admin Suscripciones")

    modulo_sel = st.radio("Módulos de Trabajo:", opciones_menu)

# =============================================================================
# RENDERIZADO DEL MÓDULO SELECCIONADO
# =============================================================================
if modulo_sel.startswith("1️⃣"):
    modulo1.render()
elif modulo_sel.startswith("2️⃣"):
    modulo2.render()
elif modulo_sel.startswith("3️⃣"):
    modulo3.render()
elif modulo_sel.startswith("4️⃣"):
    modulo4.render()
elif modulo_sel.startswith("5️⃣"):
    modulo5.render()
elif modulo_sel.startswith("6️⃣"):
    modulo6.render()
elif modulo_sel.startswith("👑") and es_admin:
    st.subheader("👑 Panel de Control de Usuarios, Demos y Pagos")
    st.caption("Administra quién tiene acceso activo, extiende periodos demo o activa suscripciones tras confirmar el pago.")

    reg = cargar_registro_cuentas()
    usuarios_dict = reg.get("usuarios", {})

    if not usuarios_dict:
        st.info("Aún no hay otros usuarios registrados.")
    else:
        for uid_item, u_data in usuarios_dict.items():
            est_u = verificar_estado_suscripcion(uid_item)
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2.2, 1.3, 1.3, 1.5])
                c1.markdown(f"**{u_data.get('nombre', 'Sin nombre')}**\n`{u_data.get('email', '')}`")
                c2.caption(f"Plan: **{u_data.get('plan', 'demo').upper()}**\nEstatus: **{est_u['motivo']}**")
                c3.caption(f"Días restantes: **{est_u['dias_restantes']}**\nVence: `{str(u_data.get('expira_el', ''))[:10]}`")

                with c4:
                    if u_data.get("email", "").lower() not in obtener_admin_emails():
                        b_act, b_sus = st.columns(2)
                        if b_act.button("✅ +30 días", key=f"act30_{uid_item}", width="stretch"):
                            actualizar_suscripcion_usuario(uid_item, "pagado", 30, "activo", "Pago mensual confirmado")
                            st.success("Activado por 30 días")
                            st.rerun()
                        if b_sus.button("⛔ Pausar", key=f"sus_{uid_item}", width="stretch"):
                            actualizar_suscripcion_usuario(uid_item, u_data.get("plan", "demo"), 0, "suspendido", "Pausado por admin")
                            st.rerun()