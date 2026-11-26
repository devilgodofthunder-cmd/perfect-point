# modulos/modulo1.py
import streamlit as st
import pandas as pd
from google import genai
from storage import guardar_datos


def render():
    db = st.session_state.db
    marca = db["marca_activa"]
    st.subheader(f"💰 Presupuesto Inteligente — {marca}")

    if "datos_presupuesto" not in db:
        db["datos_presupuesto"] = {}

    def inicializar_marca(nombre_marca):
        if nombre_marca not in db["datos_presupuesto"]:
            db["datos_presupuesto"][nombre_marca] = {
                "conceptos": [
                    {
                        "Concepto": "Pauta Digital (Meta/Google)",
                        "Frecuencia": "Mensual",
                        "Monto_Periodo": 6000.0,
                        "Presupuesto_Mensual": 6000.0,
                        "Presupuesto_Anual": 72000.0
                    },
                    {
                        "Concepto": "Producción Audiovisual",
                        "Frecuencia": "Trimestral",
                        "Monto_Periodo": 10500.0,
                        "Presupuesto_Mensual": 3500.0,
                        "Presupuesto_Anual": 42000.0
                    }
                ],
                "gastos_reales": []
            }
            guardar_datos(db)

    inicializar_marca(marca)
    datos = db["datos_presupuesto"][marca]

    # Memoria temporal para Deshacer
    if "ultimo_concepto_eliminado" not in st.session_state:
        st.session_state.ultimo_concepto_eliminado = None

    # --- BOTÓN DESHACER ---
    if st.session_state.ultimo_concepto_eliminado and st.session_state.ultimo_concepto_eliminado.get("marca") == marca:
        rec = st.session_state.ultimo_concepto_eliminado
        col_undo1, col_undo2 = st.columns([3, 1])
        col_undo1.info(f"Partida eliminada recientemente: **{rec['concepto']['Concepto']}**")
        if col_undo2.button("↩️ Deshacer / Restaurar"):
            datos["conceptos"].append(rec["concepto"])
            guardar_datos(db)
            st.session_state.ultimo_concepto_eliminado = None
            st.success("Concepto restaurado exitosamente.")
            st.rerun()

    # --- ENTRADA DE DATOS ---
    col_izq, col_der = st.columns(2)

    with col_izq:
        with st.expander("📝 Proyectar Concepto con Periodicidad", expanded=False):
            concepto = st.text_input("Concepto o partida:")
            frecuencia = st.selectbox(
                "Periodicidad del presupuesto:",
                ["Mensual", "Bimestral (cada 2 meses)", "Trimestral (cada 3 meses)", "Semestral (cada 6 meses)", "Pago único / Anual"]
            )
            monto_periodo = st.number_input("Monto presupuestado por periodo ($):", min_value=0.0, step=100.0)

            # Cálculo automático según la frecuencia
            if frecuencia == "Mensual":
                p_mensual = monto_periodo
                p_anual = monto_periodo * 12
            elif frecuencia.startswith("Bimestral"):
                p_mensual = round(monto_periodo / 2, 2)
                p_anual = monto_periodo * 6
            elif frecuencia.startswith("Trimestral"):
                p_mensual = round(monto_periodo / 3, 2)
                p_anual = monto_periodo * 4
            elif frecuencia.startswith("Semestral"):
                p_mensual = round(monto_periodo / 6, 2)
                p_anual = monto_periodo * 2
            else:  # Pago único / Anual
                p_mensual = round(monto_periodo / 12, 2)
                p_anual = monto_periodo

            c_sub1, c_sub2 = st.columns(2)
            c_sub1.caption(f"Equivalente mensual: **${p_mensual:,.2f}**")
            c_sub2.caption(f"Costo anual total: **${p_anual:,.2f}**")

            if st.button("Guardar en Presupuesto"):
                if concepto and monto_periodo > 0:
                    if any(c["Concepto"] == concepto for c in datos["conceptos"]):
                        st.warning("Ese concepto ya existe en la lista.")
                    else:
                        datos["conceptos"].append({
                            "Concepto": concepto,
                            "Frecuencia": frecuencia.split(" ")[0],
                            "Monto_Periodo": monto_periodo,
                            "Presupuesto_Mensual": p_mensual,
                            "Presupuesto_Anual": p_anual
                        })
                        guardar_datos(db)
                        st.success(f"Concepto '{concepto}' guardado.")
                        st.rerun()

    with col_der:
        with st.expander("🧾 Registrar Pago Real / Cobertura y Gastos Compartidos", expanded=False):
            lista_conceptos = [c["Concepto"] for c in datos["conceptos"]]
            concepto_pago = st.selectbox("Asignar al concepto:", lista_conceptos if lista_conceptos else ["Sin conceptos"])
            monto_real = st.number_input("Monto pagado total ($):", min_value=0.0, step=50.0)

            p_c1, p_c2 = st.columns(2)
            mes_pago = p_c1.selectbox("Mes en que se pagó:", ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"])
            cobertura = p_c2.selectbox(
                "Cobertura del pago:",
                ["1 mes (Mensual)", "2 meses (Bimestral)", "3 meses (Trimestral)", "6 meses (Semestral)", "Pago único / Todo el año"]
            )

            archivo = st.file_uploader("Subir comprobante:", type=["pdf", "png", "jpg", "jpeg"])

            dividir_gasto = st.checkbox("¿Compartir este gasto con otras marcas?")
            otras_marcas_disponibles = [m for m in db["marcas"].keys() if m != marca]
            marcas_seleccionadas = []

            if dividir_gasto:
                if otras_marcas_disponibles:
                    marcas_seleccionadas = st.multiselect(
                        "Marcas hermanas participantes:",
                        otras_marcas_disponibles
                    )
                    total_participantes = 1 + len(marcas_seleccionadas)
                    cuota = monto_real / total_participantes if total_participantes > 0 else monto_real
                    st.info(f"Dividido entre {total_participantes} marcas: **${cuota:,.2f} cada una**.")
                else:
                    st.warning("No hay más marcas registradas para compartir.")

            if st.button("Guardar Pago"):
                if lista_conceptos and monto_real > 0:
                    nombre_archivo = archivo.name if archivo else "Sin archivo"
                    tipo_cobertura = cobertura.split(" ")[0] + (" meses" if "meses" in cobertura else " mes")
                    if "año" in cobertura:
                        tipo_cobertura = "Anual / Único"

                    if dividir_gasto and marcas_seleccionadas:
                        participantes = 1 + len(marcas_seleccionadas)
                        monto_dividido = round(monto_real / participantes, 2)

                        datos["gastos_reales"].append({
                            "Concepto": f"{concepto_pago} (Compartido)",
                            "Monto": monto_dividido,
                            "Mes": mes_pago,
                            "Cobertura": tipo_cobertura,
                            "Comprobante": nombre_archivo,
                            "Nota": f"Dividido con: {', '.join(marcas_seleccionadas)}"
                        })

                        for m_dest in marcas_seleccionadas:
                            inicializar_marca(m_dest)
                            db["datos_presupuesto"][m_dest]["gastos_reales"].append({
                                "Concepto": f"{concepto_pago} (Compartido)",
                                "Monto": monto_dividido,
                                "Mes": mes_pago,
                                "Cobertura": tipo_cobertura,
                                "Comprobante": nombre_archivo,
                                "Nota": f"Gasto originado por {marca}"
                            })
                        guardar_datos(db)
                        st.success("Gasto compartido y distribuido con éxito.")
                    else:
                        datos["gastos_reales"].append({
                            "Concepto": concepto_pago,
                            "Monto": monto_real,
                            "Mes": mes_pago,
                            "Cobertura": tipo_cobertura,
                            "Comprobante": nombre_archivo,
                            "Nota": "Directo"
                        })
                        guardar_datos(db)
                        st.success("Pago registrado correctamente.")
                    st.rerun()

    # --- MÉTRICAS DE CONTROL FINANCIERO ---
    df_conceptos = pd.DataFrame(datos["conceptos"])
    df_gastos = pd.DataFrame(datos["gastos_reales"])

    total_mensual = df_conceptos["Presupuesto_Mensual"].sum() if not df_conceptos.empty else 0.0
    total_anual = df_conceptos["Presupuesto_Anual"].sum() if not df_conceptos.empty else 0.0
    total_gastado = df_gastos["Monto"].sum() if not df_gastos.empty else 0.0

    st.markdown("---")
    m1, m2, m3 = st.columns(3)
    m1.metric("Presupuesto Mensual Base (Equivalente)", f"${total_mensual:,.2f}")
    m2.metric("Total Gastado Acumulado", f"${total_gastado:,.2f}")
    m3.metric("Presupuesto Anual Techo", f"${total_anual:,.2f}")

    if total_mensual > 0:
        if total_gastado > total_anual:
            st.error(f"🚨 **Exceso Crítico:** Se ha superado el presupuesto anual por ${(total_gastado - total_anual):,.2f}.")
        elif total_gastado > total_mensual:
            remanente_anual = total_anual - total_gastado
            st.warning(f"⚠️ **Atención:** Los pagos acumulados (${total_gastado:,.2f}) superan la base mensual de referencia (${total_mensual:,.2f}), lo cual es usual si registraste pagos semestrales, trimestrales o anuales. **Te restan ${remanente_anual:,.2f} disponibles dentro del techo anual**.")
        else:
            st.success("✅ **Finanzas estables:** Todos los gastos están dentro de los márgenes previstos.")

    # --- TABLAS DE DETALLE ---
    t1, t2 = st.columns([5, 5])
    with t1:
        st.write("### Lista de Presupuestos")
        if datos["conceptos"]:
            h1, h2, h3, h4, h5 = st.columns([3, 2, 2, 2, 1])
            h1.caption("**Concepto**")
            h2.caption("**Frecuencia**")
            h3.caption("**Mensual Eq.**")
            h4.caption("**Techo Anual**")
            h5.caption("**Borrar**")

            for i, item in enumerate(datos["conceptos"]):
                c_nom, c_frec, c_men, c_anu, c_del = st.columns([3, 2, 2, 2, 1])
                c_nom.write(item["Concepto"])
                c_frec.write(item.get("Frecuencia", "Mensual"))
                c_men.write(f"${item['Presupuesto_Mensual']:,.2f}")
                c_anu.write(f"${item['Presupuesto_Anual']:,.2f}")

                if c_del.button("🗑️", key=f"del_btn_{i}", help=f"Eliminar {item['Concepto']}"):
                    st.session_state.ultimo_concepto_eliminado = {
                        "marca": marca,
                        "concepto": item
                    }
                    datos["conceptos"].pop(i)
                    guardar_datos(db)
                    st.rerun()
        else:
            st.info("No hay conceptos presupuestados.")

    with t2:
        st.write("### Historial de Pagos y Comprobantes")
        if not df_gastos.empty:
            st.dataframe(df_gastos, width="stretch")
        else:
            st.info("No hay pagos registrados para esta marca.")

    # --- AUDITORÍA IA GEMINI ---
    st.markdown("---")
    st.write("### 🤖 Auditoría Financiera con Gemini")

    if st.button("Analizar flujo y salud presupuestaria con IA"):
        api_key = db.get("gemini_api_key")
        if not api_key:
            st.warning("⚠️ El servicio de Inteligencia Artificial no tiene configurada la clave GEMINI_API_KEY en el servidor.")
        else:
            with st.spinner("Gemini está evaluando los ciclos y anticipos de pago..."):
                try:
                    client = genai.Client(api_key=api_key)
                    prompt = f"""
                    Eres director financiero y estratega de marketing.
                    Analiza la salud presupuestaria de la marca '{marca}':
- Base presupuestaria mensual prorrateada: ${total_mensual}
- Techo presupuestario anual: ${total_anual}
- Total gastado en caja: ${total_gastado}
- Detalle de conceptos proyectados con sus frecuencias: {df_conceptos.to_dict(orient='records')}
- Detalle de pagos reales efectuados con su cobertura: {df_gastos.to_dict(orient='records')}

                    Instrucciones:
1. Revisa si los gastos que parecen 'altos' corresponden en realidad a coberturas extendidas (trimestrales, semestrales o anuales).
2. Diagnostica si el ritmo de ejecución compromete el techo anual.
3. Entrega 3 recomendaciones puntuales de optimización de flujo de caja para esta marca y sus marcas vinculadas.
                    """
                    response = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=prompt
                    )
                    st.markdown(response.text)
                except Exception as e:
                    st.error(f"Error con la API de Gemini: {str(e)}")