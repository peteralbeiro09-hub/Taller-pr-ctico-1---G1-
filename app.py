"""CLI de la demostración de EcoMarket.

Uso:
    python app.py probar
    python app.py pedido "<mensaje>" --version v1|v2|v3|v4 [--mostrar-prompt]
    python app.py devolucion "<mensaje>" --version v1|v2|v3|v4 [--mostrar-prompt]
    python app.py chat
    python app.py evaluar [--solo pedidos|devoluciones|cadena]
"""

import argparse
import json
import sys
from datetime import datetime

from src import cadena, contexto, prompts
from src.config import DIR_RESULTADOS, FECHA_REFERENCIA, ErrorConfiguracion, cargar_toml
from src.llm import ErrorLLM, RespuestaPendiente, activar_cache, completar, nombre_modelo

MENSAJE_FALLA_JSON = "No pude procesar tu solicitud automáticamente; un agente humano revisará tu caso."
PENDIENTE = "⏳ Pendiente: aún no se ha obtenido del modelo (límite del endpoint gratuito)."


def cmd_probar(_args):
    print(f"Modelo: {nombre_modelo()}")
    print(completar([{"role": "user", "content": "Hola"}]))


def _mostrar_prompt(mensajes):
    for m in mensajes:
        print(f"--- [{m['role']}] ---\n{m['content']}\n")


def cmd_pedido(args):
    mensajes = prompts.construir_mensajes("pedidos", args.version, args.mensaje)
    if args.mostrar_prompt:
        _mostrar_prompt(mensajes)
        return
    print(completar(mensajes))


def cmd_devolucion(args):
    if args.mostrar_prompt:
        _mostrar_prompt(prompts.construir_mensajes("devoluciones", args.version, args.mensaje))
        return
    if args.version != "v4":
        print(completar(prompts.construir_mensajes("devoluciones", args.version, args.mensaje)))
        return
    resultado = cadena.responder_devolucion_v4(args.mensaje)
    # En v4 el razonamiento nunca se muestra al cliente: solo respuesta_cliente.
    print(resultado["respuesta_cliente"] if resultado["ok"] else MENSAJE_FALLA_JSON)


def cmd_chat(_args):
    print(f"Asistente virtual de EcoMarket ({nombre_modelo()}). Escribe 'salir' para terminar.\n")
    while True:
        try:
            mensaje = input("Tú: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if mensaje.lower() in ("salir", "exit", "quit"):
            break
        if not mensaje:
            continue
        resultado = cadena.responder(mensaje)
        print(f"EcoMarket: {resultado['respuesta']}")
        print(f"   [ruta: {resultado['ruta']}]\n")


# ---------- evaluar ----------

def _celda(texto) -> str:
    """Hace que un texto quepa en una celda de tabla Markdown."""
    if texto is None:
        return ""
    return str(texto).strip().replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def _encabezado(titulo: str, descripcion: str) -> list[str]:
    return [
        f"# {titulo}",
        "",
        f"- **Modelo:** `{nombre_modelo()}` · **Temperatura:** 0 · **Fecha de referencia:** {FECHA_REFERENCIA}",
        f"- **Ejecutado:** {datetime.now():%Y-%m-%d %H:%M}",
        "- Salidas reales generadas por `python app.py evaluar`, sin edición manual.",
        "",
        descripcion,
        "",
    ]


def _evaluar_ejercicio(ejercicio: str, casos: list[dict]) -> list[str]:
    config = cargar_toml(ejercicio)
    titulo = "Resultados — Solicitud de pedidos" if ejercicio == "pedidos" else "Resultados — Devoluciones"
    lineas = _encabezado(titulo, "Cada caso se ejecuta con las cuatro versiones del prompt. "
                                 "La línea **Esperado** es el criterio de observación con que se analiza cada respuesta.")
    lineas += ["## Versiones", ""] + [f"- **{v}:** {config[v]['descripcion']}" for v in prompts.VERSIONES] + [""]

    for caso in casos:
        lineas += [f"## {caso['id']} — {caso['caso']}", "",
                   f"**Consulta:** {caso['consulta']}", "",
                   f"**Esperado:** {caso['esperado']}", ""]
        if ejercicio == "devoluciones":
            lineas += ["| Versión | Respuesta al cliente | Decisión (v4) | Razonamiento interno (v4, no se muestra al cliente) |",
                       "|---|---|---|---|"]
        else:
            lineas += ["| Versión | Respuesta |", "|---|---|"]

        for version in prompts.VERSIONES:
            print(f"  {caso['id']} {version}...", file=sys.stderr)
            try:
                celdas = _celdas_version(ejercicio, version, caso)
            except RespuestaPendiente:
                celdas = [PENDIENTE] + (["", ""] if ejercicio == "devoluciones" else [])
            lineas.append(f"| {version} | " + " | ".join(_celda(c) for c in celdas) + " |")
        lineas.append("")
    return lineas


def _celdas_version(ejercicio: str, version: str, caso: dict) -> list[str]:
    """Celdas de la fila de una versión. En devoluciones v4 se separan respuesta, decisión y razonamiento."""
    if ejercicio == "devoluciones" and version == "v4":
        r = cadena.responder_devolucion_v4(caso["consulta"])
        if r["ok"]:
            return [r["respuesta_cliente"], r["decision"], r["razonamiento"]]
        return [f"{MENSAJE_FALLA_JSON} (JSON no interpretable)", "", f"Salida cruda: {r['crudo']}"]
    celdas = [completar(prompts.construir_mensajes(ejercicio, version, caso["consulta"]))]
    if ejercicio == "devoluciones":
        celdas += ["", ""]
    return celdas


def _evaluar_cadena(casos: list[dict]) -> list[str]:
    lineas = _encabezado("Resultados — Cadena de prompts",
                         "Cada consulta pasa por la cadena completa: clasificar → enrutar → "
                         "responder con v4 o escalar a un agente humano.")
    lineas += ["| Caso | Consulta | Clasificación | Ruta | Respuesta al cliente |", "|---|---|---|---|---|"]
    for caso in casos:
        print(f"  cadena {caso['id']}...", file=sys.stderr)
        try:
            r = cadena.responder(caso["consulta"])
        except RespuestaPendiente:
            lineas.append(f"| {caso['id']} — {_celda(caso['caso'])} | {_celda(caso['consulta'])} | | | {PENDIENTE} |")
            continue
        clasif = json.dumps(r["clasificacion"], ensure_ascii=False) if r["clasificacion"] else "(no interpretable)"
        lineas.append(f"| {caso['id']} — {_celda(caso['caso'])} | {_celda(caso['consulta'])} | "
                      f"`{_celda(clasif)}` | {_celda(r['ruta'])} | {_celda(r['respuesta'])} |")
    return lineas


def cmd_evaluar(args):
    casos = contexto.casos_prueba()
    DIR_RESULTADOS.mkdir(exist_ok=True)
    activar_cache(DIR_RESULTADOS / ".cache_respuestas.json", solo_cache=args.parcial)
    trabajos = {
        "pedidos": lambda: _evaluar_ejercicio("pedidos", casos["pedidos"]),
        "devoluciones": lambda: _evaluar_ejercicio("devoluciones", casos["devoluciones"]),
        "cadena": lambda: _evaluar_cadena(casos["pedidos"] + casos["devoluciones"]),
    }
    for nombre, trabajo in trabajos.items():
        if args.solo and args.solo != nombre:
            continue
        print(f"Evaluando {nombre}...", file=sys.stderr)
        archivo = DIR_RESULTADOS / f"resultados_{nombre}.md"
        archivo.write_text("\n".join(trabajo()) + "\n", encoding="utf-8")
        print(f"Escrito results/{archivo.name}")


def main():
    # La consola de Windows no usa UTF-8 por defecto; sin esto se dañan tildes y eñes.
    for flujo in (sys.stdout, sys.stderr, sys.stdin):
        flujo.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Asistente de atención al cliente de EcoMarket")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("probar", help="Envía 'Hola' al modelo configurado en .env").set_defaults(func=cmd_probar)

    for nombre, func, ayuda in (("pedido", cmd_pedido, "Consulta el estado de un pedido"),
                                ("devolucion", cmd_devolucion, "Solicitud de devolución de un producto")):
        p = sub.add_parser(nombre, help=ayuda)
        p.add_argument("mensaje", help="Mensaje del cliente")
        p.add_argument("--version", choices=prompts.VERSIONES, default="v4")
        p.add_argument("--mostrar-prompt", action="store_true", help="Muestra los mensajes sin llamar al modelo")
        p.set_defaults(func=func)

    sub.add_parser("chat", help="Conversación usando la cadena completa").set_defaults(func=cmd_chat)
    p = sub.add_parser("evaluar", help="Corre v1-v4 y la cadena sobre los casos de prueba y escribe results/")
    p.add_argument("--solo", choices=("pedidos", "devoluciones", "cadena"))
    p.add_argument("--parcial", action="store_true",
                   help="No llama al modelo: escribe los resultados con las respuestas reales ya guardadas "
                        "y marca las faltantes como pendientes")
    p.set_defaults(func=cmd_evaluar)

    args = parser.parse_args()
    try:
        args.func(args)
    except (ErrorConfiguracion, ErrorLLM) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
