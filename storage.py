import json
import os

ARCHIVO_BD = "datos_marketing.json"

DATOS_POR_DEFECTO = {
    "gemini_api_key": "",
    "marcas": {
        "Zona Auto Estrena": {"grupo": "Grupo Automotriz", "enlace": "Zona Seminuevos"},
        "Zona Seminuevos": {"grupo": "Grupo Automotriz", "enlace": "Zona Auto Estrena"}
    },
    "marca_activa": "Zona Auto Estrena",
    "datos_presupuesto": {
        "Zona Auto Estrena": {
            "conceptos": [
                {"Concepto": "Pauta Digital (Meta/Google)", "Presupuesto_Mensual": 6000.0, "Presupuesto_Anual": 72000.0},
                {"Concepto": "Producción Audiovisual", "Presupuesto_Mensual": 3500.0, "Presupuesto_Anual": 42000.0}
            ],
            "gastos_reales": []
        },
        "Zona Seminuevos": {
            "conceptos": [
                {"Concepto": "Pauta Digital (Meta/Google)", "Presupuesto_Mensual": 5000.0, "Presupuesto_Anual": 60000.0}
            ],
            "gastos_reales": []
        }
    }
}

def cargar_datos():
    if not os.path.exists(ARCHIVO_BD):
        guardar_datos(DATOS_POR_DEFECTO)
        return DATOS_POR_DEFECTO
    try:
        with open(ARCHIVO_BD, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DATOS_POR_DEFECTO

def guardar_datos(datos):
    with open(ARCHIVO_BD, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=4)