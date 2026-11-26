# app.py
import streamlit as st
from storage import cargar_datos, guardar_datos
from modulos import modulo1, modulo2, modulo3, modulo4, modulo5, modulo6
import recordatorios

st.set_page_config(
    page_title="Plataforma de Marketing",
    page_icon="📈",
    layout="wide"
)

# Cargar base de datos local permanente
if "db" not in st.session_state:
    st.session_state.db = cargar_datos()

db = st.session_state.db

# --- MODO PORTAL EXTERNO PARA EVENTOS (SIN ACCESO A OTROS MÓDULOS) ---
if "evento_externo" in st.query_params:
    modulo4.render_portal_externo()
    st.stop()

if "confirmar_borrado_marca" not in st.session_state:
    st.session_state.confirmar_borrado_marca = False

# --- BARRA LATERAL IZQUIERDA ---
with st.sidebar:
    st.header("⚙️ Configuración")
    
    # 1. TOKEN IA CON BOTÓN DE GUARDADO PERMANENTE
    st.subheader("🔑 Token IA (Gemini)")
    token_actual = db.get("gemini_api_key", "")
    token_input = st.text_input(
        "Ingresa tu API Key:",
        value=token_actual,
        type="password",
        placeholder="AIzaSy..."
    )
    
    if st.button("💾 Guardar Token"):
        db["gemini_api_key"] = token_input.strip()
        guardar_datos(db)
        st.success("¡Token guardado permanentemente!")
        st.rerun()

    if db.get("gemini_api_key"):
        st.success("IA conectada globalmente")
    else:
        st.caption("Guarda tu token para habilitar auditorías con IA.")

    st.markdown("---")

    # 2. GESTIÓN Y BORRADO DE MARCAS
    st.subheader("🏢 Gestión de Marcas")
    lista_marcas = list(db["marcas"].keys())
    
    if db.get("marca_activa") not in lista_marcas and lista_marcas:
        db["marca_activa"] = lista_marcas[0]
        guardar_datos(db)

    marca_sel = st.selectbox(
        "Marca activa:",
        lista_marcas,
        index=lista_marcas.index(db["marca_activa"]) if db["marca_activa"] in lista_marcas else 0
    )
    if marca_sel != db["marca_activa"]:
        db["marca_activa"] = marca_sel
        guardar_datos(db)
        st.rerun()

    info_marca = db["marcas"].get(db["marca_activa"], {})
    if info_marca.get("enlace"):
        st.info(f"🔗 Marca vinculada: **{info_marca['enlace']}**")

    st.write("---")
    if not st.session_state.confirmar_borrado_marca:
        if st.button("🗑️ Borrar esta marca", type="secondary"):
            if len(lista_marcas) <= 1:
                st.error("No puedes eliminar la única marca existente.")
            else:
                st.session_state.confirmar_borrado_marca = True
                st.rerun()
    else:
        st.warning(f"⚠️ ¿Estás seguro de borrar permanentemente la marca **'{db['marca_activa']}'** y todos sus registros?")
        c_si, c_no = st.columns(2)
        with c_si:
            if st.button("Sí, borrar", type="primary"):
                marca_a_eliminar = db["marca_activa"]
                del db["marcas"][marca_a_eliminar]
                if marca_a_eliminar in db.get("datos_presupuesto", {}):
                    del db["datos_presupuesto"][marca_a_eliminar]
                for m_key, m_val in db["marcas"].items():
                    if m_val.get("enlace") == marca_a_eliminar:
                        m_val["enlace"] = None
                
                db["marca_activa"] = list(db["marcas"].keys())[0]
                guardar_datos(db)
                st.session_state.confirmar_borrado_marca = False
                st.success(f"Marca {marca_a_eliminar} eliminada.")
                st.rerun()
        with c_no:
            if st.button("Cancelar"):
                st.session_state.confirmar_borrado_marca = False
                st.rerun()

    with st.expander("➕ Añadir / Enlazar Marca"):
        nueva_marca = st.text_input("Nombre de la nueva marca:")
        marca_relacionada = st.selectbox("Vincular con marca hermana:", ["Ninguna"] + lista_marcas)
        grupo_pertenencia = st.text_input("Holding / Grupo (opcional):", placeholder="Ej. Automotriz")
        
        if st.button("Guardar Marca"):
            if nueva_marca and nueva_marca not in db["marcas"]:
                db["marcas"][nueva_marca] = {
                    "grupo": grupo_pertenencia if grupo_pertenencia else "General",
                    "enlace": marca_relacionada if marca_relacionada != "Ninguna" else None
                }
                db["marca_activa"] = nueva_marca
                guardar_datos(db)
                st.success(f"Marca {nueva_marca} creada.")
                st.rerun()

# --- PANTALLA PRINCIPAL DIVIDIDA: MÓDULOS (IZQUIERDA) + RECORDATORIOS (DERECHA) ---
col_principal, col_derecha = st.columns([3.3, 1.2], gap="large")

with col_principal:
    st.title("Plataforma de Marketing")
    st.caption(f"Trabajando actualmente en: **{db['marca_activa']}**")

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "Presupuesto", 
        "Creacion de Contenido", 
        "Programación de Publicaciones", 
        "Eventos", 
        "Resultados",
        "🗂️ Almacén Creativo"
    ])

    with tab1:
        modulo1.render()

    with tab2:
        modulo2.render()

    with tab3:
        modulo3.render()

    with tab4:
        modulo4.render()

    with tab5:
        modulo5.render()

    with tab6:
        modulo6.render()

with col_derecha:
    recordatorios.render_panel_derecho()