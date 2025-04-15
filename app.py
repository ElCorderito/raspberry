import os
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, abort, url_for
import requests
import requests_cache
import pandas as pd
import pytz

app = Flask(__name__)

WEATHER_UPDATE_REQUESTED = False

# Este dict se puede poner globalmente o dentro de la función
WEATHER_ICON_MAP = {
    0: "images/soleado.png",
    1: "images/mayormente_despejado.png",
    2: "images/parcialmente_nublado.png",
    3: "images/nublado.png",
    45: "images/niebla.png",
    48: "images/niebla.png",
    51: "images/llovizna_ligera.png",
    53: "images/llovizna_ligera.png",
    55: "images/llovizna_ligera.png",
    61: "images/lluvia.png",
    63: "images/lluvia.png",
    65: "images/lluvia.png",
    80: "images/llovizna_ligera.png",
    81: "images/llovizna_ligera.png",
    82: "images/llovizna_ligera.png",
    95: "images/tormenta.png",
    96: "images/tormenta.png",
    99: "images/tormenta.png"
}

# Carpeta donde guardas tu data.json
DATA_FILE = os.path.join('data', 'data.json')

# Variable global en memoria para la última notificación
LAST_NOTIFICATION = None

@app.route('/branch/<int:branch_id>/request_weather_update', methods=['POST'])
def request_weather_update(branch_id):
    global WEATHER_UPDATE_REQUESTED
    # (Verificas si el branch existe, etc. si gustas)
    WEATHER_UPDATE_REQUESTED = True
    return jsonify({"status": "weather_update_requested"})

@app.route('/branch/<int:branch_id>/check_weather_flag')
def check_weather_flag(branch_id):
    global WEATHER_UPDATE_REQUESTED
    if WEATHER_UPDATE_REQUESTED:
        return jsonify({"update": True})
    else:
        return jsonify({"update": False})

@app.route('/branch/<int:branch_id>/clear_weather_flag', methods=['POST'])
def clear_weather_flag(branch_id):
    global WEATHER_UPDATE_REQUESTED
    WEATHER_UPDATE_REQUESTED = False
    return jsonify({"status": "cleared"})


# ------------------------------------------------------------------------
# Funciones para leer/escribir data.json
# ------------------------------------------------------------------------
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"branches": []}
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ------------------------------------------------------------------------
# Ruta principal: Listado de sucursales
# ------------------------------------------------------------------------
@app.route('/branches')
def list_branches():
    data = load_data()
    branches = data.get("branches", [])
    return jsonify(branches)

# ------------------------------------------------------------------------
# Detalle de sucursal -> Usa la plantilla branch_detail.html
# ------------------------------------------------------------------------
@app.route('/branch/<int:branch_id>')
def branch_detail(branch_id):
    data = load_data()
    branch = next((b for b in data["branches"] if b["id"] == branch_id), None)
    if not branch:
        abort(404, "Sucursal no encontrada")

    weather_data = branch.get("weather_data", {})
    daily_forecast = weather_data.get("daily", [])
    hourly_forecast = weather_data.get("hourly", [])

    return render_template('branch_detail.html',
                           branch=branch,
                           daily_forecast_json=daily_forecast,
                           hourly_forecast_json=hourly_forecast)

# ------------------------------------------------------------------------
# Endpoint para recibir una nueva tasa de cambio
# ------------------------------------------------------------------------
@app.route('/update_exchange_rate', methods=['POST'])
def update_exchange_rate():
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON inválido"}), 400

    branch_id = data.get("branch_id")
    buy = data.get("buy")
    sell = data.get("sell")

    content = load_data()
    branch = next((b for b in content["branches"] if b["id"] == branch_id), None)
    if not branch:
        return jsonify({"error": "Sucursal no encontrada"}), 404

    branch["exchange_rate"]["buy"] = buy
    branch["exchange_rate"]["sell"] = sell

    save_data(content)

    return jsonify({"message": "Tipo de cambio actualizado", "branch": branch}), 200

# ------------------------------------------------------------------------
# Endpoint para obtener el TC actual de una sucursal (Marquee horizontal)
# ------------------------------------------------------------------------
@app.route('/branch/<int:branch_id>/current_exchange_rate')
def current_exchange_rate(branch_id):
    data = load_data()
    branch = next((b for b in data["branches"] if b["id"] == branch_id), None)
    if not branch:
        return jsonify({"error": "Sucursal no encontrada"}), 404
    return jsonify(branch["exchange_rate"])

# ------------------------------------------------------------------------
# Endpoints para la NOTIFICACIÓN
# ------------------------------------------------------------------------
@app.route('/notify', methods=['POST'])
def notify():
    """
    Recibe:
    {
      "branch_id": <int>,
      "message": "Caja X",
      "sound_id": <int>  // Ej: 1..10
    }
    """
    global LAST_NOTIFICATION
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON inválido"}), 400

    branch_id = data.get("branch_id")
    message = data.get("message")
    sound_id = data.get("sound_id")

    content = load_data()
    branch = next((b for b in content["branches"] if b["id"] == branch_id), None)
    if not branch:
        return jsonify({"error": "Sucursal no encontrada"}), 404

    LAST_NOTIFICATION = {
        "branch_id": branch_id,
        "message": message,
        "sound_id": sound_id
    }
    return jsonify({"status": "ok"}), 200

@app.route('/branch/<int:branch_id>/current_notification')
def current_notification(branch_id):
    global LAST_NOTIFICATION
    if LAST_NOTIFICATION and LAST_NOTIFICATION["branch_id"] == branch_id:
        return jsonify({
            "message":  LAST_NOTIFICATION["message"],
            "sound_id": LAST_NOTIFICATION["sound_id"]
        })
    else:
        return jsonify({"message": None, "sound_id": None})

@app.route('/branch/<int:branch_id>/clear_notification', methods=['POST'])
def clear_notification(branch_id):
    global LAST_NOTIFICATION
    if LAST_NOTIFICATION and LAST_NOTIFICATION["branch_id"] == branch_id:
        LAST_NOTIFICATION = None
    return jsonify({"status": "cleared"})

# ------------------------------------------------------------------------
# Endpoint para actualizar/obtener datos de clima (similar a tu ejemplo)
# ------------------------------------------------------------------------
@app.route('/branch/<int:branch_id>/get_weather_data')
def get_weather_data(branch_id):
    content = load_data()
    branch = next((b for b in content["branches"] if b["id"] == branch_id), None)
    if not branch:
        return jsonify({"error": "Sucursal no encontrada"}), 404

    # Llamamos a la API de Open-Meteo, tal como tenías
    cache_session = requests_cache.CachedSession('.cache', expire_after=3600)
    url = "https://api.open-meteo.com/v1/forecast"
    tz_la = pytz.timezone("America/Los_Angeles")
    today_la = datetime.now(tz_la).date()

    # --- Obtener hourly data ---
    params_hourly = {
        "latitude": 33.2553,
        "longitude": -116.5664,
        "hourly": ["temperature_2m", "weather_code"],
        "timezone": "America/Los_Angeles",
        "start_date": today_la.strftime("%Y-%m-%d"),
        "end_date": (today_la + timedelta(days=1)).strftime("%Y-%m-%d")
    }
    resp_hourly = cache_session.get(url, params=params_hourly)
    if not resp_hourly.ok:
        return jsonify({"error": "Fallo al obtener datos hourly"}), 500
    data_hourly = resp_hourly.json().get("hourly", {})
    time_data = data_hourly.get("time", [])
    temp_data = data_hourly.get("temperature_2m", [])
    code_data = data_hourly.get("weather_code", [])

    hourly_records = []
    for i, t_str in enumerate(time_data):
        dt_local = pd.to_datetime(t_str)
        record = {
            "date": dt_local.strftime("%Y-%m-%d"),
            "time": dt_local.isoformat(),
            "temperature_2m": float(temp_data[i]) if i < len(temp_data) else None,
            "weather_code": int(code_data[i]) if i < len(code_data) else None
        }
        hourly_records.append(record)

    # --- Encontrar la hora más cercana a "ahora" ---
    now = datetime.now(tz_la)
    closest_record = None
    min_diff = timedelta.max
    for h in hourly_records:
        dt = pd.to_datetime(h["time"]).tz_localize(None)
        diff = abs(now.replace(tzinfo=None) - dt)
        if diff < min_diff:
            min_diff = diff
            closest_record = h

    current_weather = {}
    if closest_record:
        # Armamos algo más “listo para mostrar”
        temp_float = closest_record["temperature_2m"]
        code = closest_record["weather_code"]
        current_weather = {
            "temperature_str": f"{temp_float:.1f}°C",
            "weather_code": code,
            "weather_icon_url": url_for('static', filename=WEATHER_ICON_MAP.get(code, 'images/default.png')),
        }
    else:
        # Por si no hay datos
        current_weather = {
            "temperature_str": "N/D",
            "weather_code": None,
            "weather_icon_url": url_for('static', filename='images/default.png')
        }

    # --- Obtener daily data ---
    params_daily = {
        "latitude": 33.2553,
        "longitude": -116.5664,
        "daily": ["weather_code", "temperature_2m_max", "temperature_2m_min"],
        "timezone": "America/Los_Angeles",
        "start_date": today_la.strftime("%Y-%m-%d"),
        "end_date": (today_la + timedelta(days=7)).strftime("%Y-%m-%d")
    }
    resp_daily = cache_session.get(url, params=params_daily)
    if not resp_daily.ok:
        return jsonify({"error": "Fallo al obtener datos daily"}), 500
    data_daily = resp_daily.json().get("daily", {})
    time_daily = data_daily.get("time", [])
    code_daily = data_daily.get("weather_code", [])
    tmax_daily = data_daily.get("temperature_2m_max", [])
    tmin_daily = data_daily.get("temperature_2m_min", [])

    daily_records = []
    # Para formatear fechas en español “día de mes”:
    # O usas locale.setlocale o un mini diccionario
    month_map = {
        1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
        7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
    }
    for i, d_str in enumerate(time_daily):
        dt_local = pd.to_datetime(d_str)
        code = code_daily[i] if i < len(code_daily) else None
        max_temp = tmax_daily[i] if i < len(tmax_daily) else None
        min_temp = tmin_daily[i] if i < len(tmin_daily) else None
        
        day = dt_local.day
        month = dt_local.month
        formatted_date = f"{day} {month_map.get(month, '???')}"

        daily_records.append({
            "formatted_date": formatted_date,
            "weather_code": code,
            "weather_icon_url": url_for('static', filename=WEATHER_ICON_MAP.get(code, 'images/default.png')),
            "max_temp_str": f"{max_temp:.1f}°C" if max_temp is not None else "N/D",
            "min_temp_str": f"{min_temp:.1f}°C" if min_temp is not None else "N/D",
        })

    final_data = {
        "last_updated": datetime.now().isoformat(),
        "current_weather": current_weather,
        "daily_forecast": daily_records
    }

    # Guardamos en el branch y persistimos
    branch["weather_data"] = final_data
    save_data(content)

    return jsonify(final_data)

# ------------------------------------------------------------------------
# Iniciar la app
# ------------------------------------------------------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
