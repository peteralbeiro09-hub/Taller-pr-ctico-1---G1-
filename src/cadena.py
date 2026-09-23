"""Cadena de prompts: clasificar la intención → enrutar en Python → responder con el prompt v4 o escalar."""

from src import prompts
from src.config import cargar_toml
from src.llm import completar

INTENCIONES = {"pedido", "devolucion", "queja", "otro"}


def clasificar(mensaje: str) -> dict | None:
    """Pide al modelo la clasificación en JSON. Devuelve None si la respuesta no es interpretable."""
    config = cargar_toml("cadena")["clasificador"]
    mensajes = [
        {"role": "system", "content": config["system"]},
        {"role": "user", "content": config["user"].replace("{consulta}", mensaje)},
    ]
    clasificacion = prompts.extraer_json(completar(mensajes))
    if not clasificacion or clasificacion.get("intencion") not in INTENCIONES:
        return None
    return clasificacion


def _escalar(mensaje: str, clasificacion: dict | None, motivo: str) -> dict:
    datos = clasificacion or {}
    resumen = (
        f"Motivo del escalamiento: {motivo}\n"
        f"Intención: {datos.get('intencion', 'desconocida')} | "
        f"Sentimiento: {datos.get('sentimiento', 'desconocido')} | "
        f"Pedido: {datos.get('numero_seguimiento') or 'no indicado'} | "
        f"Producto: {datos.get('producto') or 'no indicado'}\n"
        f"Mensaje original: {mensaje}"
    )
    return {
        "ruta": f"humano ({motivo})",
        "clasificacion": clasificacion,
        "respuesta": cargar_toml("cadena")["escalamiento"]["cliente"],
        "resumen_agente": resumen,
    }


def responder_devolucion_v4(mensaje: str) -> dict:
    """Ejecuta devoluciones v4. El razonamiento se devuelve para auditoría, pero nunca se muestra al cliente."""
    crudo = completar(prompts.construir_mensajes("devoluciones", "v4", mensaje))
    datos = prompts.extraer_json(crudo)
    if not datos or not datos.get("respuesta_cliente"):
        return {"ok": False, "crudo": crudo}
    return {
        "ok": True,
        "decision": datos.get("decision"),
        "razonamiento": datos.get("razonamiento"),
        "respuesta_cliente": datos["respuesta_cliente"],
    }


def responder(mensaje: str) -> dict:
    """Clasifica, enruta y responde. Ante cualquier duda, escala a un agente humano."""
    clasificacion = clasificar(mensaje)
    if clasificacion is None:
        return _escalar(mensaje, None, "clasificación no interpretable")

    intencion = clasificacion["intencion"]
    if clasificacion.get("sentimiento") == "negativo":
        return _escalar(mensaje, clasificacion, "sentimiento negativo")
    if intencion in ("queja", "otro"):
        return _escalar(mensaje, clasificacion, f"intención {intencion}")

    if intencion == "pedido":
        respuesta = completar(prompts.construir_mensajes("pedidos", "v4", mensaje))
        return {"ruta": "pedidos v4", "clasificacion": clasificacion, "respuesta": respuesta}

    resultado = responder_devolucion_v4(mensaje)
    if not resultado["ok"]:
        return _escalar(mensaje, clasificacion, "JSON de devoluciones no interpretable")
    return {"ruta": "devoluciones v4", "clasificacion": clasificacion, "respuesta": resultado["respuesta_cliente"]}
