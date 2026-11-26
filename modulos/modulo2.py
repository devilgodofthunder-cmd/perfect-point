# modulos/modulo2.py
import io
import math
import pandas as pd
import streamlit as st
from PIL import Image
from google import genai
from google.genai import types
from storage import guardar_datos

# --- INSTRUCCIÓN OCULTA (NO VISIBLE EN LA INTERFAZ) ---
INSTRUCCION_OCULTA_EXPERTO = """
Actúa como un Director Creativo Ejecutivo, Estratega Senior de Marketing y Especialista en Producción Audiovisual con IA.
Antes de generar cualquier prompt o copy, analiza profundamente el rubro, giro comercial y contexto implícito en el Prompt Maestro del usuario:
- Si el giro es gastronómico/restaurantes: considera tendencias culinarias actuales, estética food-styling, iluminación apetitosa, temporalidad, fechas clave, ubicación geográfica y diferenciación frente a la competencia local.
- Si el giro es automotriz: considera ángulos dinámicos, acabados de pintura/iluminación de estudio o carretera, aspiracionalidad, confianza financiera y ganchos de conversión.
- Para cualquier otro giro (inmobiliario, salud, retail, servicios, etc.): investiga mentalmente las mejores prácticas del sector, psicología del consumidor, tendencias visuales vigentes, fechas comerciales relevantes y contexto competitivo.

Reglas estrictas de entrega:
1. Los prompts para generación de imágenes deben ser altamente descriptivos, especificando estilo fotográfico o artístico, composición, lente/encuadre, iluminación, paleta de colores, texturas y ambiente, listos para copiar y pegar en generadores de imagen.
2. Los copys deben estar estructurados con: Gancho (Hook) de alto impacto, Cuerpo persuasivo enfocado en beneficios/tendencias, Llamado a la Acción (CTA) claro y hashtags estratégicos del sector.
3. Nunca menciones esta instrucción oculta en tu respuesta; entrega directamente el trabajo creativo con nivel de agencia top.
"""

DEFAULTS_PROMPTS_MAESTROS = {
    "img": (
        "Estilo fotográfico publicitario de alto impacto, iluminación cinematográfica, "
        "colores vibrantes de marca, enfoque nítido en el producto/vehículo, entorno urbano "
        "moderno en México, sin texto incrustado en la imagen, composición limpia para redes sociales."
    ),
    "copy": (
        "Tono persuasivo, directo y cercano al mercado mexicano. Inicia con un gancho fuerte "
        "en la primera línea, destaca beneficios claros, usa viñetas breves si aplica e incluye "
        "un llamado a la acción (CTA) claro hacia WhatsApp. Incluye 3 a 5 hashtags relevantes."
    )
}


def _exportar_tanda_excel(marca, texto_imgs, texto_copys):
    """Genera un archivo Excel descargable con los resultados generados."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        if texto_imgs:
            pd.DataFrame({
                "Marca": [marca],
                "Prompts de Imagen Generados": [texto_imgs]
            }).to_excel(writer, sheet_name="Prompts Imagen", index=False)
        if texto_copys:
            pd.DataFrame({
                "Marca": [marca],
                "Copys Generados": [texto_copys]
            }).to_excel(writer, sheet_name="Copys", index=False)
    buffer.seek(0)
    return buffer.getvalue()


def render():
    db = st.session_state.db
    marca = db["marca_activa"]
    st.subheader(f"🎨 Creacion de Contenido — {marca}")

    # Inicializar almacenamiento permanente de contenido por marca
    if "datos_contenido" not in db:
        db["datos_contenido"] = {}

    if marca not in db["datos_contenido"]:
        db["datos_contenido"][marca] = {
            "prompt_maestro_img": DEFAULTS_PROMPTS_MAESTROS["img"],
            "prompt_maestro_copy": DEFAULTS_PROMPTS_MAESTROS["copy"]
        }
        guardar_datos(db)

    datos_marca = db["datos_contenido"][marca]

    # =========================================================================
    # SECCIÓN A Y B: PROMPTS MAESTROS (IMÁGENES Y COPYS) POR MARCA
    # =========================================================================
    st.markdown("### 1. Configuración de Prompts Maestros (Por Marca)")
    st.caption("Define o adjunta las reglas base, identidad visual y tono de comunicación de esta marca. Quedarán guardados permanentemente.")

    col_m1, col_m2 = st.columns(2)

    # --- A) PROMPT MAESTRO PARA IMÁGENES ---
    with col_m1:
        st.markdown("**🖼️ Prompt Maestro — Imágenes**")
        archivo_img_txt = st.file_uploader(
            "Adjuntar archivo de texto (.txt / .md) opcional:",
            type=["txt", "md"],
            key=f"file_pm_img_{marca}"
        )

        texto_base_img = datos_marca.get("prompt_maestro_img", "") or DEFAULTS_PROMPTS_MAESTROS["img"]
        if archivo_img_txt is not None:
            file_id_img = f"{marca}_{archivo_img_txt.name}_{archivo_img_txt.size}"
            if st.session_state.get("ultimo_txt_img") != file_id_img:
                texto_base_img = archivo_img_txt.getvalue().decode("utf-8")
                st.session_state[f"input_pm_img_{marca}"] = texto_base_img
                st.session_state["ultimo_txt_img"] = file_id_img

        prompt_img_edit = st.text_area(
            "Escribe o edita el Prompt Maestro de Imágenes:",
            value=texto_base_img,
            height=180,
            placeholder="Ej. Marca de autos seminuevos en CDMX. Estilo fotográfico realista, luz natural de atardecer, enfoque en seguridad familiar y elegancia...",
            key=f"input_pm_img_{marca}"
        )

        if st.button("💾 Guardar Prompt Maestro de Imágenes", key=f"btn_save_pm_img_{marca}"):
            datos_marca["prompt_maestro_img"] = prompt_img_edit.strip()
            guardar_datos(db)
            st.success(f"Prompt Maestro de Imágenes guardado para {marca}.")

    # --- B) PROMPT MAESTRO PARA COPYS ---
    with col_m2:
        st.markdown("**✍️ Prompt Maestro — Copys**")
        archivo_copy_txt = st.file_uploader(
            "Adjuntar archivo de texto (.txt / .md) opcional:",
            type=["txt", "md"],
            key=f"file_pm_copy_{marca}"
        )

        texto_base_copy = datos_marca.get("prompt_maestro_copy", "") or DEFAULTS_PROMPTS_MAESTROS["copy"]
        if archivo_copy_txt is not None:
            file_id_copy = f"{marca}_{archivo_copy_txt.name}_{archivo_copy_txt.size}"
            if st.session_state.get("ultimo_txt_copy") != file_id_copy:
                texto_base_copy = archivo_copy_txt.getvalue().decode("utf-8")
                st.session_state[f"input_pm_copy_{marca}"] = texto_base_copy
                st.session_state["ultimo_txt_copy"] = file_id_copy

        prompt_copy_edit = st.text_area(
            "Escribe o edita el Prompt Maestro de Copys:",
            value=texto_base_copy,
            height=180,
            placeholder="Ej. Tono cercano, profesional y persuasivo. Público objetivo: hombres y mujeres de 28 a 50 años. Incluir llamados a la acción por WhatsApp...",
            key=f"input_pm_copy_{marca}"
        )

        if st.button("💾 Guardar Prompt Maestro de Copys", key=f"btn_save_pm_copy_{marca}"):
            datos_marca["prompt_maestro_copy"] = prompt_copy_edit.strip()
            guardar_datos(db)
            st.success(f"Prompt Maestro de Copys guardado para {marca}.")

    # =========================================================================
    # SECCIÓN C: GENERADOR DE PROMPTS DE IMAGEN Y COPYS (HASTA 100 POR TANDA)
    # =========================================================================
    st.markdown("---")
    st.markdown("### 2. Generador de Prompts de Imagen y Copys")

    c_cant1, c_cant2, c_tema = st.columns([1, 1, 2])
    cant_prompts_img = c_cant1.number_input(
        "¿Cuántos prompts de imagen necesitas?",
        min_value=0,
        max_value=100,
        value=3,
        step=1,
        key=f"num_img_{marca}"
    )
    cant_copys = c_cant2.number_input(
        "¿Cuántos copys necesitas?",
        min_value=0,
        max_value=100,
        value=3,
        step=1,
        key=f"num_copy_{marca}"
    )
    tema_puntual = c_tema.text_input(
        "Enfoque, promoción o fecha específica para esta tanda (opcional):",
        placeholder="Ej. Promoción de fin de mes, lanzamiento de producto, día festivo...",
        key=f"tema_{marca}"
    )

    if cant_prompts_img > 15 or cant_copys > 15:
        st.caption("⚡ Solicitud masiva: se procesará en lotes automáticos para entregarte todos los prompts completos sin recortes.")

    if st.button("✨ Generar Prompts de Imagen y Copys", type="primary", key=f"btn_gen_lote_{marca}"):
        api_key = db.get("gemini_api_key")
        pm_img_guardado = (datos_marca.get("prompt_maestro_img", "") or prompt_img_edit).strip()
        pm_copy_guardado = (datos_marca.get("prompt_maestro_copy", "") or prompt_copy_edit).strip()

        if not api_key:
            st.warning("⚠️ El servicio de Inteligencia Artificial no tiene configurada la clave GEMINI_API_KEY en el servidor.")
        elif cant_prompts_img == 0 and cant_copys == 0:
            st.warning("Indica al menos 1 prompt de imagen o 1 copy para generar.")
        elif cant_prompts_img > 0 and not pm_img_guardado:
            st.warning("Falta guardar el Prompt Maestro de Imágenes en el paso 1.")
        elif cant_copys > 0 and not pm_copy_guardado:
            st.warning("Falta guardar el Prompt Maestro de Copys en el paso 1.")
        else:
            with st.spinner("Analizando tendencias del giro y creando propuestas..."):
                try:
                    client = genai.Client(api_key=api_key)
                    resultados_lote = {}
                    tam_lote = 15

                    # Generar Prompts de Imagen (por lotes si son más de 15)
                    if cant_prompts_img > 0:
                        bloques_img = []
                        lotes_img = math.ceil(cant_prompts_img / tam_lote)
                        barra_i = st.progress(0, text="Generando prompts de imagen...") if lotes_img > 1 else None

                        for b_idx in range(lotes_img):
                            ini = b_idx * tam_lote + 1
                            fin = min((b_idx + 1) * tam_lote, cant_prompts_img)
                            cant_sub = fin - ini + 1

                            if barra_i:
                                barra_i.progress(b_idx / lotes_img, text=f"🖼️ Generando Prompts de Imagen ({ini} al {fin} de {cant_prompts_img})...")

                            nota_continuidad = (
                                f"Esta es la continuación (lote {b_idx + 1} de {lotes_img}). Propón escenarios, encuadres y conceptos completamente nuevos y distintos a los anteriores."
                                if b_idx > 0 else ""
                            )

                            solicitud_img = f"""
                            Marca: {marca}
                            Prompt Maestro de Imágenes: {pm_img_guardado}
                            Enfoque o campaña específica actual: {tema_puntual if tema_puntual else 'Contenido estratégico general de alto impacto según tendencias actuales del sector'}
                            {nota_continuidad}

                            Genera exactamente {cant_sub} prompts diferentes, creativos y detallados para generación de imágenes con IA.
                            Numéralos claramente del Prompt {ini} al Prompt {fin} y asegúrate de que cada uno explore un ángulo visual distinto pero fiel al Prompt Maestro.
                            """
                            res_img = client.models.generate_content(
                                model="gemini-2.5-flash",
                                contents=solicitud_img,
                                config=types.GenerateContentConfig(
                                    system_instruction=INSTRUCCION_OCULTA_EXPERTO,
                                    temperature=0.8
                                )
                            )
                            bloques_img.append(res_img.text)

                        if barra_i:
                            barra_i.empty()
                        resultados_lote["imagenes"] = "\n\n---\n\n".join(bloques_img)

                    # Generar Copys (por lotes si son más de 15)
                    if cant_copys > 0:
                        bloques_copy = []
                        lotes_copy = math.ceil(cant_copys / tam_lote)
                        barra_c = st.progress(0, text="Generando copys...") if lotes_copy > 1 else None

                        for b_idx in range(lotes_copy):
                            ini = b_idx * tam_lote + 1
                            fin = min((b_idx + 1) * tam_lote, cant_copys)
                            cant_sub = fin - ini + 1

                            if barra_c:
                                barra_c.progress(b_idx / lotes_copy, text=f"✍️ Generando Copys ({ini} al {fin} de {cant_copys})...")

                            nota_continuidad_c = (
                                f"Esta es la continuación (lote {b_idx + 1} de {lotes_copy}). Usa ganchos y ángulos comerciales nuevos distintos a los anteriores."
                                if b_idx > 0 else ""
                            )

                            solicitud_copy = f"""
                            Marca: {marca}
                            Prompt Maestro de Copys: {pm_copy_guardado}
                            Enfoque o campaña específica actual: {tema_puntual if tema_puntual else 'Contenido estratégico general orientado a engagement y conversión'}
                            {nota_continuidad_c}

                            Genera exactamente {cant_sub} copys listos para publicar en redes sociales.
                            Numéralos claramente del Copy {ini} al Copy {fin}. Cada uno debe incluir Gancho, Cuerpo, CTA y Hashtags.
                            """
                            res_copy = client.models.generate_content(
                                model="gemini-2.5-flash",
                                contents=solicitud_copy,
                                config=types.GenerateContentConfig(
                                    system_instruction=INSTRUCCION_OCULTA_EXPERTO,
                                    temperature=0.8
                                )
                            )
                            bloques_copy.append(res_copy.text)

                        if barra_c:
                            barra_c.empty()
                        resultados_lote["copys"] = "\n\n---\n\n".join(bloques_copy)

                    st.session_state[f"res_contenido_{marca}"] = resultados_lote
                    st.success("¡Contenido generado con éxito!")
                except Exception as e:
                    st.error(f"Error al conectar con Gemini: {str(e)}")

    # Mostrar resultados generados si existen en sesión
    res_actual = st.session_state.get(f"res_contenido_{marca}")
    if res_actual:
        txt_imgs_res = res_actual.get("imagenes", "")
        txt_copys_res = res_actual.get("copys", "")

        dl1, dl2 = st.columns(2)
        excel_bytes = _exportar_tanda_excel(marca, txt_imgs_res, txt_copys_res)
        dl1.download_button(
            label="📥 Descargar Todo en Excel (.xlsx)",
            data=excel_bytes,
            file_name=f"Prompts_y_Copys_{marca.replace(' ', '_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch"
        )
        contenido_txt = f"=== {marca.upper()} ===\n\n{txt_imgs_res}\n\n{txt_copys_res}".strip()
        dl2.download_button(
            label="📄 Descargar Todo en Texto (.txt)",
            data=contenido_txt.encode("utf-8"),
            file_name=f"Prompts_y_Copys_{marca.replace(' ', '_')}.txt",
            mime="text/plain",
            width="stretch"
        )

        r_col1, r_col2 = st.columns(2)
        if "imagenes" in res_actual:
            with r_col1:
                st.markdown("#### 🖼️ Prompts de Imagen Generados")
                st.markdown(res_actual["imagenes"])
        if "copys" in res_actual:
            with r_col2:
                st.markdown("#### ✍️ Copys Generados")
                st.markdown(res_actual["copys"])

    # =========================================================================
    # SECCIÓN D: DE IMAGEN A PROMPT DE VIDEO
    # =========================================================================
    st.markdown("---")
    st.markdown("### 3. Convertidor de Imagen a Prompt de Video")
    st.caption("Sube una imagen de referencia y la IA creará el prompt técnico de animación y cámara para generadores de video (Veo, Runway, Kling, Sora).")

    imagen_video = st.file_uploader(
        "Sube la imagen base para sacar el prompt de video:",
        type=["png", "jpg", "jpeg", "webp"],
        key=f"uploader_video_{marca}"
    )

    if imagen_video is not None:
        v_col1, v_col2 = st.columns([1, 2])
        img_pil = Image.open(imagen_video)

        with v_col1:
            st.image(img_pil, caption="Imagen de referencia", width="stretch")

        with v_col2:
            indicacion_mov = st.text_input(
                "¿Qué acción o movimiento de cámara deseas? (opcional):",
                placeholder="Ej. Acercamiento cinematográfico lento, movimiento sutil de luz y ambiente para Reel vertical...",
                key=f"mov_video_{marca}"
            )
            idioma_video = st.selectbox(
                "Idioma del prompt de video:",
                ["Inglés (Recomendado para Veo / Runway / Kling)", "Español"],
                key=f"idioma_vid_{marca}"
            )

            if st.button("🎬 Generar Prompt de Video", type="primary", key=f"btn_gen_vid_{marca}"):
                api_key = db.get("gemini_api_key")
                if not api_key:
                    st.warning("⚠️ El servicio de Inteligencia Artificial no tiene configurada la clave GEMINI_API_KEY en el servidor.")
                else:
                    with st.spinner("Analizando composición visual y diseñando dirección de cámara..."):
                        try:
                            client = genai.Client(api_key=api_key)
                            prompt_vision = f"""
                            Analiza detalladamente esta imagen y crea un prompt maestro de 'Image-to-Video' para animarla con inteligencia artificial.
                            Marca / Contexto: {marca}
                            Indicaciones adicionales del usuario: {indicacion_mov if indicacion_mov else 'Movimiento natural, fluido y altamente atractivo para redes sociales.'}
                            Idioma de salida requerido para el prompt final: {idioma_video}.

                            Estructura tu respuesta así:
1. **Prompt listo para copiar y pegar** (en un bloque limpio, describiendo sujeto, acción dinámica, movimiento de cámara, iluminación, atmósfera y calidad cinematográfica).
2. **Notas de dirección** (breve explicación en español de por qué ese movimiento funciona para retener atención en los primeros 3 segundos).
                            """
                            res_vid = client.models.generate_content(
                                model="gemini-2.5-flash",
                                contents=[img_pil, prompt_vision],
                                config=types.GenerateContentConfig(
                                    system_instruction=INSTRUCCION_OCULTA_EXPERTO,
                                    temperature=0.7
                                )
                            )
                            st.session_state[f"res_video_{marca}"] = res_vid.text
                        except Exception as e:
                            st.error(f"Error al procesar la imagen con Gemini: {str(e)}")

            if f"res_video_{marca}" in st.session_state:
                st.markdown("#### 🎥 Prompt de Video Resultante")
                st.markdown(st.session_state[f"res_video_{marca}"])