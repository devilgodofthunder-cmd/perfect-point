# storage.py
import copy
import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent
CARPETA_USUARIOS = BASE_DIR / "datos_usuarios"
CARPETA_USUARIOS.mkdir(exist_ok=True)
ARCHIVO_CUENTAS = CARPETA_USUARIOS / "registro_cuentas.json"
ARCHIVO_LEGACY = BASE_DIR / "datos_marketing.json"

DIAS_DEMO_DEFAULT = 3

DATOS_POR_DEFECTO = {
    "gemini_api_key": "",
    "marcas": {
        "Mi Marca": {"grupo": "General", "enlace": ""}
    },
    "marca_activa": "Mi Marca",
    "datos_presupuesto": {
        "Mi Marca": {
            "conceptos": [],
            "gastos_reales": []
        }
    }
}


def obtener_api_key_servidor() -> str:
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return str(st.secrets["GEMINI_API_KEY"]).strip()
    except Exception:
        pass
    return os.getenv("GEMINI_API_KEY", "").strip()


def obtener_admin_emails() -> list[str]:
    """Lee correos administradores desde st.secrets['ADMIN_EMAILS'] (separados por coma)."""
    raw = ""
    try:
        if "ADMIN_EMAILS" in st.secrets:
            raw = str(st.secrets["ADMIN_EMAILS"])
    except Exception:
        pass
    if not raw:
        raw = os.getenv("ADMIN_EMAILS", "")
    return [e.strip().lower() for e in raw.split(",") if e.strip()]


def generar_user_id(email: str) -> str:
    clean = str(email).strip().lower()
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()[:16]


def obtener_user_id_actual() -> str:
    try:
        uid = st.session_state.get("auth_user_id", "")
        if uid:
            return uid
        ukey = st.session_state.get("auth_user_key", "invitado")
        return generar_user_id(ukey)
    except Exception:
        return generar_user_id("invitado")


def obtener_carpeta_media_usuario(subcarpeta: str, user_id: str | None = None) -> str:
    """Crea y devuelve una subcarpeta aislada por usuario para archivos multimedia y adjuntos."""
    uid = user_id or obtener_user_id_actual()
    ruta = BASE_DIR / subcarpeta / uid
    ruta.mkdir(parents=True, exist_ok=True)
    return str(ruta)


def obtener_archivo_usuario(user_id: str | None = None) -> Path:
    uid = user_id or obtener_user_id_actual()
    return CARPETA_USUARIOS / f"user_{uid}.json"


# =============================================================================
# GESTIÓN DE CUENTAS, DEMO Y SUSCRIPCIONES
# =============================================================================
def cargar_registro_cuentas() -> dict:
    if not ARCHIVO_CUENTAS.exists():
        return {"usuarios": {}}
    try:
        with open(ARCHIVO_CUENTAS, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "usuarios" not in data or not isinstance(data["usuarios"], dict):
            return {"usuarios": {}}
        return data
    except Exception:
        return {"usuarios": {}}


def guardar_registro_cuentas(registro: dict) -> None:
    with open(ARCHIVO_CUENTAS, "w", encoding="utf-8") as f:
        json.dump(registro, f, ensure_ascii=False, indent=4)


def autenticar_o_registrar_usuario(nombre_usuario: str, email: str) -> dict:
    """
    Registra una cuenta nueva con demo gratuita o recupera la existente.
    Si es el primer administrador y existe datos_marketing.json, migra sus datos automáticamente.
    """
    email_norm = str(email).strip().lower()
    nombre_clean = str(nombre_usuario).strip()
    uid = generar_user_id(email_norm)
    ahora = datetime.now()

    registro = cargar_registro_cuentas()
    usuarios = registro["usuarios"]
    admins = obtener_admin_emails()
    es_admin = email_norm in admins

    if uid not in usuarios:
        vence_demo = ahora + timedelta(days=DIAS_DEMO_DEFAULT)
        usuarios[uid] = {
            "user_id": uid,
            "nombre": nombre_clean,
            "email": email_norm,
            "fecha_registro": ahora.isoformat(),
            "ultimo_acceso": ahora.isoformat(),
            "plan": "admin" if es_admin else "demo",
            "estatus": "activo",
            "expira_el": (ahora + timedelta(days=3650)).isoformat() if es_admin else vence_demo.isoformat(),
            "notas_admin": ""
        }
        guardar_registro_cuentas(registro)

        # Si el administrador entra por primera vez y existe datos_marketing.json, migrarlo
        archivo_u = obtener_archivo_usuario(uid)
        if es_admin and ARCHIVO_LEGACY.exists() and not archivo_u.exists():
            try:
                with open(ARCHIVO_LEGACY, "r", encoding="utf-8") as f_leg:
                    datos_leg = json.load(f_leg)
                guardar_datos(datos_leg, user_id=uid)
            except Exception:
                pass
    else:
        if nombre_clean:
            usuarios[uid]["nombre"] = nombre_clean
        usuarios[uid]["ultimo_acceso"] = ahora.isoformat()
        if es_admin:
            usuarios[uid]["plan"] = "admin"
            usuarios[uid]["estatus"] = "activo"
        guardar_registro_cuentas(registro)

    return verificar_estado_suscripcion(uid)


def verificar_estado_suscripcion(user_id: str) -> dict:
    """Evalúa si el usuario tiene acceso activo (admin, demo vigente o plan pagado vigente)."""
    registro = cargar_registro_cuentas()
    info = registro["usuarios"].get(user_id)
    if not info:
        return {"acceso_permitido": False, "motivo": "Cuenta no encontrada", "dias_restantes": 0, "info": {}}

    email_norm = info.get("email", "").lower()
    if email_norm in obtener_admin_emails() or info.get("plan") == "admin":
        return {"acceso_permitido": True, "motivo": "Administrador", "dias_restantes": 999, "info": info}

    if info.get("estatus") == "suspendido":
        return {"acceso_permitido": False, "motivo": "Cuenta suspendida por administración", "dias_restantes": 0, "info": info}

    try:
        expira_dt = datetime.fromisoformat(info.get("expira_el", ""))
    except Exception:
        expira_dt = datetime.now() - timedelta(seconds=1)

    ahora = datetime.now()
    if ahora <= expira_dt:
        segundos_rest = (expira_dt - ahora).total_seconds()
        dias_rest = max(1, int((segundos_rest + 86399) // 86400))
        return {
            "acceso_permitido": True,
            "motivo": "Vigente",
            "dias_restantes": dias_rest,
            "info": info
        }

    # Si venció, actualizar estatus a vencido
    if info.get("estatus") != "vencido":
        info["estatus"] = "vencido"
        guardar_registro_cuentas(registro)

    return {
        "acceso_permitido": False,
        "motivo": "Periodo de prueba o suscripción vencida",
        "dias_restantes": 0,
        "info": info
    }


def actualizar_suscripcion_usuario(user_id: str, nuevo_plan: str, dias_vigencia: int, estatus: str = "activo", notas: str = "") -> bool:
    """Permite al administrador activar planes pagados, extender demos o suspender cuentas."""
    registro = cargar_registro_cuentas()
    if user_id not in registro["usuarios"]:
        return False
    u = registro["usuarios"][user_id]
    u["plan"] = nuevo_plan
    u["estatus"] = estatus
    u["expira_el"] = (datetime.now() + timedelta(days=int(dias_vigencia))).isoformat()
    u["notas_admin"] = notas
    guardar_registro_cuentas(registro)
    return True


def listar_todos_los_user_ids() -> list[str]:
    """Devuelve todos los IDs de usuario con archivo guardado para tareas en segundo plano."""
    ids = []
    for p in CARPETA_USUARIOS.glob("user_*.json"):
        uid = p.stem.replace("user_", "")
        if uid:
            ids.append(uid)
    return ids


# =============================================================================
# LECTURA Y ESCRITURA AISLADA POR USUARIO
# =============================================================================
def cargar_datos(user_id: str | None = None):
    archivo = obtener_archivo_usuario(user_id)
    if not archivo.exists():
        datos = copy.deepcopy(DATOS_POR_DEFECTO)
        datos["gemini_api_key"] = obtener_api_key_servidor()
        guardar_datos(datos, user_id=user_id)
        return datos

    try:
        with open(archivo, "r", encoding="utf-8") as f:
            datos = json.load(f)
        datos["gemini_api_key"] = obtener_api_key_servidor()
        return datos
    except Exception:
        datos = copy.deepcopy(DATOS_POR_DEFECTO)
        datos["gemini_api_key"] = obtener_api_key_servidor()
        return datos


def guardar_datos(datos, user_id: str | None = None):
    archivo = obtener_archivo_usuario(user_id)
    datos_a_guardar = copy.deepcopy(datos)
    # Nunca guardar la API Key del servidor dentro de los JSON de usuarios
    datos_a_guardar["gemini_api_key"] = ""
    with open(archivo, "w", encoding="utf-8") as f:
        json.dump(datos_a_guardar, f, ensure_ascii=False, indent=4)