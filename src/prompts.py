"""Arma la lista de mensajes para cada ejercicio y versión, y lee de forma robusta el JSON del modelo."""

import json
import re

from src import contexto
from src.config import FECHA_REFERENCIA, cargar_toml

VERSIONES = ("v1", "v2", "v3", "v4")


def _rellenar(plantilla: str, valores: dict) -> str:
    """Reemplaza solo los marcadores conocidos; así las llaves de los JSON de ejemplo no se tocan."""
    for clave, valor in valores.items():
        plantilla = plantilla.replace("{" + clave + "}", valor)
    return plantilla


def _valores(consulta: str) -> dict:
    return {
        "consulta": consulta,
        "pedidos": contexto.pedidos_texto(),
        "catalogo": contexto.catalogo_texto(),
        "politica": contexto.politica_texto(),
        "fecha": FECHA_REFERENCIA,
    }


def construir_mensajes(ejercicio: str, version: str, consulta: str) -> list[dict]:
    """Devuelve los mensajes: un único system al inicio (solo v4) y luego user/assistant alternados."""
    prompt = cargar_toml(ejercicio)[version]
    valores = _valores(consulta)

    mensajes = []
    if "system" in prompt:
        mensajes.append({"role": "system", "content": _rellenar(prompt["system"], valores)})
    for ejemplo in prompt.get("ejemplos", []):
        mensajes.append({"role": "user", "content": ejemplo["user"]})
        mensajes.append({"role": "assistant", "content": ejemplo["assistant"]})
    mensajes.append({"role": "user", "content": _rellenar(prompt["user"], valores)})

    validar_alternancia(mensajes)
    return mensajes


def validar_alternancia(mensajes: list[dict]) -> None:
    """Varias plantillas de modelos abiertos fallan con system intercalados o dos user seguidos."""
    roles = [m["role"] for m in mensajes]
    if "system" in roles[1:]:
        raise ValueError("El mensaje system solo puede ir al inicio.")
    conversacion = roles[1:] if roles[0] == "system" else roles
    for i, rol in enumerate(conversacion):
        esperado = "user" if i % 2 == 0 else "assistant"
        if rol != esperado:
            raise ValueError(f"Alternancia inválida en la posición {i}: {roles}")
    if conversacion[-1] != "user":
        raise ValueError("El último mensaje debe ser del usuario.")


def extraer_json(texto: str) -> dict | None:
    """Quita bloques de código y toma el primer objeto {...}. Devuelve None si no se puede interpretar."""
    limpio = re.sub(r"```(?:json)?", "", texto)
    inicio = limpio.find("{")
    if inicio == -1:
        return None
    try:
        objeto, _ = json.JSONDecoder().raw_decode(limpio[inicio:])
    except json.JSONDecodeError:
        return None
    return objeto if isinstance(objeto, dict) else None
