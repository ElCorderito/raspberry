import os
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, abort, url_for
import requests
import requests_cache
import pandas as pd
import pytz

app = Flask(__name__)

# Carpeta donde guardas tu data.json
DATA_FILE = os.path.join('data', 'data.json')

# Variable global en memoria para la última notificación
LAST_NOTIFICATION = None

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
      "message": "¡Favor de pasar a la Caja X!",
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

    # (Se podría checar si hay datos frescos, etc.)
    cache_session = requests_cache.CachedSession('.cache', expire_after=3600)
    url = "https://api.open-meteo.com/v1/forecast"
    tz_la = pytz.timezone("America/Los_Angeles")
    today_la = datetime.now(tz_la).date()

    # Hourly
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

    # Daily
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
    for i, d_str in enumerate(time_daily):
        dt_local = pd.to_datetime(d_str)
        record = {
            "date": dt_local.strftime("%Y-%m-%d"),
            "weather_code": int(code_daily[i]) if i < len(code_daily) else None,
            "temperature_2m_max": float(tmax_daily[i]) if i < len(tmax_daily) else None,
            "temperature_2m_min": float(tmin_daily[i]) if i < len(tmin_daily) else None,
        }
        daily_records.append(record)

    final_data = {
        "last_updated": datetime.now().isoformat(),
        "hourly": hourly_records,
        "daily": daily_records
    }

    branch["weather_data"] = final_data
    save_data(content)
    return jsonify(final_data)

# ------------------------------------------------------------------------
# Iniciar la app
# ------------------------------------------------------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
