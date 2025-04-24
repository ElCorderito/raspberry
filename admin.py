# admin.py
import os, json, uuid
from flask import Blueprint, render_template, request, jsonify, send_from_directory

MEDIA_DIR = os.path.abspath('signage_media')
PLAYLIST  = os.path.abspath('static/playlist.json')

admin = Blueprint('admin', __name__, url_prefix='/admin')

# admin.py (solo esta función cambia)
@admin.route('/')
def panel():
    try:
        with open(PLAYLIST, 'r', encoding='utf-8') as f:
            items = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        items = []
        # Asegurarse de que el archivo exista con [] para la próxima vez
        os.makedirs(os.path.dirname(PLAYLIST), exist_ok=True)
        with open(PLAYLIST, 'w', encoding='utf-8') as f:
            json.dump(items, f)
    return render_template('admin_panel.html', items=items)

@admin.post('/upload')
def upload():
    f = request.files['file']
    ext = os.path.splitext(f.filename)[1]
    name = f'{uuid.uuid4().hex}{ext}'
    f.save(os.path.join(MEDIA_DIR, name))
    return jsonify({'file': name})

@admin.post('/save_playlist')
def save_playlist():
    with open(PLAYLIST, 'w') as f:
        json.dump(request.get_json(), f, indent=2, ensure_ascii=False)
    return '', 204

@admin.route('/media/<path:fname>')
def media(fname):
    return send_from_directory(MEDIA_DIR, fname)
