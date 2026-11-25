#!/usr/bin/env python3
"""
Vigila la agenda de diagnóstico de MNTK «Микрохирургия глаза» (San Petersburgo)
y avisa en cuanto aparece un hueco libre.

Uso:
    python3 vigilar_citas_mntk.py                # cada 2 minutos, ambos departamentos
    python3 vigilar_citas_mntk.py --intervalo 60 # cada 60 segundos
    python3 vigilar_citas_mntk.py --depto 153    # solo departamento nº1

Aviso opcional por Telegram (para enterarte en el móvil):
    export TG_TOKEN="123456:ABC..."   # token de tu bot (@BotFather)
    export TG_CHAT="123456789"        # tu chat id (@userinfobot)

Solo usa la biblioteca estándar de Python: no hace falta instalar nada.
El script SOLO consulta la disponibilidad; la reserva la haces tú en la web
(el formulario exige código de verificación).
"""

import argparse
import http.cookiejar
import json
import os
import platform
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime

BASE = "http://reg.mntk.spb.ru"          # la web redirige de https a http
PAGINA = BASE + "/diagnostics/"
API = BASE + "/diagnostics/index.php"

DEPARTAMENTOS = {
    "153": "Консультативно-диагностическое отделение №1",
    "17": "Консультативно-диагностическое отделение №2",
}

cookies = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
opener.addheaders = [
    ("User-Agent", "Mozilla/5.0 (vigilar-citas; consulta cada pocos minutos)"),
    ("X-Requested-With", "XMLHttpRequest"),
    ("Referer", PAGINA),
]


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def post(datos):
    cuerpo = urllib.parse.urlencode(datos).encode()
    req = urllib.request.Request(
        API, data=cuerpo,
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
    )
    with opener.open(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def abrir_sesion():
    with opener.open(PAGINA, timeout=30) as r:
        r.read()


def dias_disponibles(depto):
    """Devuelve [(fecha, dateId, n_huecos)] con huecos > 0.
    En la respuesta, param = nº de huecos; 0 = lleno; -1 = no hay consulta."""
    datos = post({"method": "getcalendar", "department": f"~{depto}~"})
    libres = []
    for it in datos.get("items", []):
        try:
            n = int(it.get("param", 0))
        except (TypeError, ValueError):
            continue
        if n > 0:
            libres.append((it["name"], it["ID"], n))
    return libres


def horas(depto, date_id):
    datos = post({"method": "gethours", "department": f"~{depto}~", "dateId": date_id})
    return [
        f"{it.get('name')} ({it.get('param')})"
        for it in datos.get("items", [])
        if str(it.get("ID")) != "0"
    ]


def avisar(texto):
    print("\a" * 3, flush=True)  # pitido en la terminal
    sistema = platform.system()
    try:
        if sistema == "Darwin":
            subprocess.run(["osascript", "-e",
                            f'display notification "{texto[:200]}" with title "¡Cita MNTK disponible!" sound name "Glass"'],
                           check=False)
            subprocess.run(["say", "Hay cita disponible"], check=False)
        elif sistema == "Windows":
            import winsound
            for _ in range(5):
                winsound.Beep(1000, 400)
        else:
            subprocess.run(["notify-send", "¡Cita MNTK disponible!", texto[:200]], check=False)
    except Exception:
        pass

    token, chat = os.environ.get("TG_TOKEN"), os.environ.get("TG_CHAT")
    if token and chat:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            cuerpo = urllib.parse.urlencode({"chat_id": chat, "text": texto + "\n" + PAGINA}).encode()
            urllib.request.urlopen(url, data=cuerpo, timeout=20).read()
        except Exception as e:
            log(f"No se pudo enviar el Telegram: {e}")

    try:
        webbrowser.open(PAGINA)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intervalo", type=int, default=120,
                    help="segundos entre consultas (por defecto 120; no bajes de 30)")
    ap.add_argument("--depto", choices=list(DEPARTAMENTOS), action="append",
                    help="departamento a vigilar (153 = nº1, 17 = nº2). Por defecto, ambos")
    ap.add_argument("--seguir", action="store_true",
                    help="seguir vigilando después de avisar (por defecto se detiene)")
    ap.add_argument("--una-vez", action="store_true",
                    help="consulta una sola vez y termina (para GitHub Actions)")
    ap.add_argument("--probar-telegram", action="store_true",
                    help="envía un mensaje de prueba por Telegram y termina")
    args = ap.parse_args()

    if args.probar_telegram:
        token, chat = os.environ.get("TG_TOKEN"), os.environ.get("TG_CHAT")
        if not (token and chat):
            log("Faltan TG_TOKEN y/o TG_CHAT. Configúralos antes de probar.")
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        cuerpo = urllib.parse.urlencode(
            {"chat_id": chat, "text": "✅ Prueba: el vigilante de citas MNTK funciona."}).encode()
        try:
            urllib.request.urlopen(url, data=cuerpo, timeout=20).read()
            log("Mensaje de prueba enviado. Revisa Telegram.")
        except Exception as e:
            log(f"Falló el envío: {e}. Revisa el token, el chat id y que hayas escrito antes a tu bot.")
        return

    deptos = args.depto or list(DEPARTAMENTOS)
    intervalo = max(30, args.intervalo)

    if args.una_vez:
        # Modo para GitHub Actions u otro programador: una consulta y termina.
        try:
            abrir_sesion()
            encontrados = []
            for d in deptos:
                for fecha, date_id, n in dias_disponibles(d):
                    try:
                        hs = horas(d, date_id)
                    except Exception:
                        hs = []
                    encontrados.append((d, fecha, n, hs))
        except Exception as e:
            log(f"ERROR al conectar con la web del hospital: {e}")
            sys.exit(1)
        if encontrados:
            lineas = [f"{DEPARTAMENTOS[d]}: {f} — {n} hueco(s) {'; '.join(hs)}"
                      for d, f, n, hs in encontrados]
            for l in lineas:
                log("LIBRE → " + l)
            avisar("\n".join(lineas))
        else:
            log("Conexión correcta. Sin huecos.")
        return

    log(f"Vigilando {', '.join(deptos)} cada {intervalo}s. Ctrl+C para parar.")
    ultimo_aviso = set()
    errores = 0

    while True:
        try:
            if not cookies:
                abrir_sesion()
            encontrados = []
            for d in deptos:
                for fecha, date_id, n in dias_disponibles(d):
                    try:
                        hs = horas(d, date_id)
                    except Exception:
                        hs = []
                    encontrados.append((d, fecha, n, hs))
            errores = 0

            if encontrados:
                clave = {(d, f) for d, f, _, _ in encontrados}
                lineas = [f"{DEPARTAMENTOS[d]}: {f} — {n} hueco(s) {'; '.join(hs)}"
                          for d, f, n, hs in encontrados]
                for l in lineas:
                    log("LIBRE → " + l)
                if clave != ultimo_aviso:
                    avisar("\n".join(lineas))
                    ultimo_aviso = clave
                if not args.seguir:
                    log("Aviso enviado. Entra ya en la web para reservar.")
                    return
            else:
                ultimo_aviso = set()
                log("Sin huecos.")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            errores += 1
            cookies.clear()
            log(f"Error ({errores}): {e}")
            if errores >= 10:
                avisar("El vigilante de citas MNTK lleva 10 errores seguidos; revisa la conexión.")
                errores = 0
        time.sleep(intervalo)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
