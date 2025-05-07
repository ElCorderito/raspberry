# app.py
import os, json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, abort, url_for
import requests, requests_cache, pandas as pd, pytz
import locale

locale.setlocale(locale.LC_TIME, 'en_US.UTF-8')   # fuerza locale inglés

app = Flask(__name__)                # 1) crea la app

from admin import admin              # 2) importa el blueprint
app.register_blueprint(admin)        # 3) lo registras


# -------------  Archivos y utilidades -----------------
DATA_FILE  = os.path.join('data', 'data.json')
NOTIF_FILE = os.path.join('data', 'notifications.json')
os.makedirs(os.path.dirname(NOTIF_FILE), exist_ok=True)
if not os.path.exists(NOTIF_FILE):
    with open(NOTIF_FILE, 'w', encoding='utf-8') as f:
        json.dump([], f)

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"branches": []}
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_notifications() -> list:
    with open(NOTIF_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_notifications(q: list):
    with open(NOTIF_FILE, 'w', encoding='utf-8') as f:
        json.dump(q, f, ensure_ascii=False, indent=2)

# -------------  Flags de clima -----------------
WEATHER_UPDATE_REQUESTED = False

@app.route('/branch/<int:branch_id>/request_weather_update', methods=['POST'])
def request_weather_update(branch_id):
    global WEATHER_UPDATE_REQUESTED
    WEATHER_UPDATE_REQUESTED = True
    return jsonify({"status": "weather_update_requested"})

@app.route('/branch/<int:branch_id>/check_weather_flag')
def check_weather_flag(branch_id):
    return jsonify({"update": WEATHER_UPDATE_REQUESTED})

@app.route('/branch/<int:branch_id>/clear_weather_flag', methods=['POST'])
def clear_weather_flag(branch_id):
    global WEATHER_UPDATE_REQUESTED
    WEATHER_UPDATE_REQUESTED = False
    return jsonify({"status": "cleared"})

# -------------  Listado y detalle de sucursales -----------------
@app.route('/branches')
def list_branches():
    return jsonify(load_data().get("branches", []))

def format_rate(rate):
    s = f"{rate:.4f}".rstrip('0').rstrip('.')
    if '.' not in s:
        s += '.000'
    elif len(s.split('.')[1]) < 3:
        s += '0' * (3 - len(s.split('.')[1]))
    return s

@app.route('/branch/<int:branch_id>')
def branch_detail(branch_id):
    data   = load_data()
    branch = next((b for b in data["branches"] if b["id"] == branch_id), None)
    if not branch:
        abort(404, "Sucursal no encontrada")

    buy, sell = branch["exchange_rate"]["buy"], branch["exchange_rate"]["sell"]
    branch["exchange_rate"]["buy_str"]  = format_rate(buy)
    branch["exchange_rate"]["sell_str"] = format_rate(sell)

    return render_template('branch_detail.html', branch=branch)

# -------------  Tipo de cambio -----------------
@app.route('/update_exchange_rate', methods=['POST'])
def update_exchange_rate():
    data = request.get_json(silent=True) or {}
    branch_id, buy, sell = data.get("branch_id"), data.get("buy"), data.get("sell")

    content = load_data()
    branch  = next((b for b in content["branches"] if b["id"] == branch_id), None)
    if not branch:
        return jsonify({"error": "Sucursal no encontrada"}), 404

    branch["exchange_rate"]["buy"], branch["exchange_rate"]["sell"] = buy, sell
    save_data(content)
    return jsonify({"message": "Tipo de cambio actualizado"}), 200

@app.route('/branch/<int:branch_id>/current_exchange_rate')
def current_exchange_rate(branch_id):
    branch = next((b for b in load_data()["branches"] if b["id"] == branch_id), None)
    if not branch:
        return jsonify({"error": "Sucursal no encontrada"}), 404
    return jsonify(branch["exchange_rate"])

# -------------  NOTIFICACIONES -----------------
@app.route('/notify', methods=['POST'])
def notify():
    data = request.get_json(silent=True) or {}
    notif = {
        "branch_id": data.get("branch_id"),
        "message":   data.get("message"),
        "sound_id":  data.get("sound_id"),
        "rotation":  data.get("rotation", 0)
    }
    q = load_notifications()
    q.append(notif)
    save_notifications(q)
    return jsonify({"status": "queued"}), 200

@app.route('/branch/<int:branch_id>/next_notification')
def next_notification(branch_id):
    q = load_notifications()
    for i, n in enumerate(q):
        if n["branch_id"] == branch_id:
            q.pop(i)
            save_notifications(q)
            return jsonify(n), 200
    return jsonify({"message": None, "sound_id": None, "rotation": 0})

# -------------  Clima (Open‑Meteo resumido) -----------------
WEATHER_ICON_MAP = { 0:"images/soleado.png", 1:"images/mayormente_despejado.png", 2:"images/parcialmente_nublado.png",
                     3:"images/nublado.png", 45:"images/niebla.png", 48:"images/niebla.png",
                     51:"images/llovizna_ligera.png", 53:"images/llovizna_ligera.png", 55:"images/llovizna_ligera.png",
                     61:"images/lluvia.png", 63:"images/lluvia.png", 65:"images/lluvia.png",
                     80:"images/llovizna_ligera.png", 81:"images/llovizna_ligera.png", 82:"images/llovizna_ligera.png",
                     95:"images/tormenta.png", 96:"images/tormenta.png", 99:"images/tormenta.png" }

@app.route('/branch/<int:branch_id>/get_weather_data')
def get_weather_data(branch_id):
    data   = load_data()
    branch = next((b for b in data["branches"] if b["id"] == branch_id), None)
    if not branch:
        return jsonify({"error": "Sucursal no encontrada"}), 404

    url   = "https://api.open-meteo.com/v1/forecast"
    tz    = pytz.timezone("America/Los_Angeles")
    day0  = datetime.now(tz).date()
    cache = requests_cache.CachedSession('.cache', expire_after=3600)

    # ---------- hourly (para el “ahora”) ----------
    p_h = {
        "latitude": 33.2553, "longitude": -116.5664,
        "hourly": ["temperature_2m", "weather_code"],
        "timezone": "America/Los_Angeles",
        "start_date": day0, "end_date": day0 + timedelta(days=1),
        "temperature_unit": "fahrenheit"
    }
    h = cache.get(url, params=p_h).json().get("hourly", {})
    now = datetime.now(tz).replace(tzinfo=None)

    best, diff = None, timedelta.max
    for t, temp, code in zip(h["time"], h["temperature_2m"], h["weather_code"]):
        d = abs(now - pd.to_datetime(t))
        if d < diff:
            best, diff = (temp, code), d
    temp_now, code_now = best
    current = {
        "temperature_str": f"{temp_now:.1f}°F",
        "weather_icon_url": url_for('static',
                                    filename=WEATHER_ICON_MAP.get(code_now, 'images/default.png'))
    }

    # ---------- daily (pronóstico 7 días) ----------
    p_d = {
        "latitude": 33.2553, "longitude": -116.5664,
        "daily": ["weather_code", "temperature_2m_max", "temperature_2m_min"],
        "timezone": "America/Los_Angeles",
        "start_date": day0, "end_date": day0 + timedelta(days=7),
        "temperature_unit": "fahrenheit"
    }
    d_json = cache.get(url, params=p_d).json().get("daily", {})

    month_es = ['enero','febrero','marzo','abril','mayo','junio',
                'julio','agosto','septiembre','octubre','noviembre','diciembre']
    daily_forecast = []
    for t, code, tmax, tmin in zip(d_json["time"],
                                d_json["weather_code"],
                                d_json["temperature_2m_max"],
                                d_json["temperature_2m_min"]):
        dt = pd.to_datetime(t)
        daily_forecast.append({
            "formatted_date": f"{dt.day} {dt.strftime('%B')}",  # «7 May», «8 May», …
            "weather_icon_url": url_for('static',
                                        filename=WEATHER_ICON_MAP.get(code, 'images/default.png')),
            "max_temp_str": f"{tmax:.1f}°F",
            "min_temp_str": f"{tmin:.1f}°F"
        })

    final = {
        "last_updated": datetime.now().isoformat(),
        "current_weather": current,
        "daily_forecast": daily_forecast
    }

    branch["weather_data"] = final
    save_data(data)
    return jsonify(final)

# -------------  Run -----------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
