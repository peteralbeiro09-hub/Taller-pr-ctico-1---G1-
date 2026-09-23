"""Carga los datos de EcoMarket y los formatea como texto para inyectarlos en los prompts."""

import json

from src.config import DIR_DATOS


def _leer_json(nombre: str):
    with open(DIR_DATOS / nombre, encoding="utf-8") as archivo:
        return json.load(archivo)


def pedidos_texto() -> str:
    """Pedidos en JSON legible: el modelo ve los campos exactos, incluidos los nulos."""
    return json.dumps(_leer_json("pedidos.json"), ensure_ascii=False, indent=2)


def catalogo_texto() -> str:
    """Una línea por producto con categoría, si es devolvible y precio."""
    catalogo = _leer_json("catalogo.json")
    lineas = [
        f"- {p['nombre']} | categoría: {p['categoria']} | "
        f"devolvible: {'sí' if p['devolvible'] else 'no'} | precio: ${p['precio']:,} COP".replace(",", ".")
        for p in catalogo["productos"]
    ]
    return "\n".join(lineas)


def politica_texto() -> str:
    return (DIR_DATOS / "politica_devoluciones.md").read_text(encoding="utf-8")


def casos_prueba() -> dict:
    return _leer_json("casos_prueba.json")
