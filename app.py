import os
import sqlite3
import requests
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, session, jsonify

app = Flask(__name__)
app.secret_key = 'clave_secreta_consultorio_dental'

# ==========================================
# 1. CONFIGURACIÓN DE SEGURIDAD Y ACCESO
# ==========================================
ADMIN_USER = "admin"
ADMIN_PASS = "1234"
ADMIN_ROUTE = "/panel-gestion-privada"

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logueado'):
            return redirect('/acceso-control')
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# 2. CONFIGURACIÓN DE CLAVE Y PROMPT DEL CHATBOT
# ==========================================
# Lee la clave de forma segura desde las variables de entorno de Render
API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

SYSTEM_INSTRUCTION = """
Eres la Recepcionista Virtual del consultorio del Dr. José Joel Arreola Rangel en Guadalajara, Jalisco.
Tu ÚNICA función es informar sobre promociones de entrada, ubicaciones, horarios y CANALIZAR de inmediato al paciente con el odontólogo para su valoración presencial.

REGLAS ESTRICTAS DE RESPUESTA:
1. NO DIAGNOSTIQUES NI EXPLIQUES TRATAMIENTOS TÉCNICOS:
   - Si el usuario pregunta por costos o detalles de tratamientos (endodoncias, coronas, implantes, extracciones, etc.), NUNCA expliques el procedimiento ni des precios aproximados.
   - Responde inmediatamente: "Por ética médica y para cuidar su salud, el Dr. Arreola necesita hacer una valoración clínica presencial con radiografía antes de dar un diagnóstico o costo exacto."

2. INFORMACIÓN PERMITIDA (Únicamente esto):
   - Limpieza Dental Ultrasonido: $400 - $600 MXN.
   - Valoración inicial: $200 MXN (o GRATIS en promociones activas).
   - Inicio de Brackets: Enganche desde $1,500 MXN.
   - Horarios: Lunes a Viernes de 9:00 AM a 8:00 PM y Sábados de 9:00 AM a 2:00 PM.

3. CANALIZACIÓN INMEDIATA (Cierre obligatorio):
   - Da respuestas directas, breves y COMPLETAS (de 2 a 4 oraciones). NUNCA dejes oraciones incompletas o cortadas.
   - Finaliza siempre indicando: "Para agendar su cita de valoración o atención inmediata, por favor presione el botón verde de WhatsApp."
"""

# ==========================================
# 3. BASE DE DATOS SQLITE
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'consultorio.db')

def obtener_conexion():
    conexion = sqlite3.connect(DB_PATH)
    conexion.row_factory = sqlite3.Row
    return conexion

def inicializar_bd():
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS citas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente TEXT,
            telefono TEXT,
            servicio TEXT,
            fecha_registro TEXT,
            estado TEXT DEFAULT 'Pendiente'
        )
    ''')
    conexion.commit()

    try:
        cursor.execute("ALTER TABLE citas ADD COLUMN fecha_registro TEXT")
        conexion.commit()
    except sqlite3.OperationalError:
        pass

    conexion.close()

inicializar_bd()

# ==========================================
# 4. RUTAS PRINCIPALES DE LA PÁGINA
# ==========================================

@app.route('/')
def inicio():
    exito = request.args.get('exito')
    paciente = request.args.get('paciente', '')
    return render_template('index.html', exito=exito, paciente=paciente)

@app.route('/agendar', methods=['POST'])
def agendar():
    nombre = request.form.get('paciente', '').strip() or 'Paciente'
    telefono = request.form.get('telefono', '').strip() or 'Sin Teléfono'
    servicio = request.form.get('servicio', '').strip() or 'Valoración General'
    
    ahora = datetime.now()
    fecha_registro = ahora.strftime("%d/%m/%Y %I:%M %p")

    conexion = obtener_conexion()
    cursor = conexion.cursor()
    cursor.execute(
        "INSERT INTO citas (paciente, telefono, servicio, fecha_registro, estado) VALUES (?, ?, ?, ?, 'Pendiente')",
        (nombre, telefono, servicio, fecha_registro)
    )
    conexion.commit()
    conexion.close()

    return redirect(f'/?exito=1&paciente={nombre}#formulario')

# ENDPOINT DEL CHATBOT - MODELO GEMINI 1.5 FLASH
@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json.get("message", "")
    
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
    
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": API_KEY
    }
    
    payload = {
        "contents": [{
            "parts": [{"text": f"{SYSTEM_INSTRUCTION}\n\nCliente dice: {user_message}"}]
        }],
        "generationConfig": {
            "maxOutputTokens": 300,
            "temperature": 0.2
        }
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()
        
        if "candidates" in data and len(data["candidates"]) > 0:
            bot_response = data["candidates"][0]["content"]["parts"][0]["text"]
            return jsonify({"response": bot_response})
        else:
            bot_response = "En este momento no puedo procesar su solicitud. Por favor, intente de nuevo o presione el botón de WhatsApp."
            
    except Exception as e:
        bot_response = "Ocurrió un inconveniente temporal con el servidor del chat. Por favor, contáctenos vía WhatsApp."
        
    return jsonify({"response": bot_response})


# ==========================================
# 5. RUTAS DE ADMINISTRACIÓN Y SEGURIDAD
# ==========================================

@app.route('/admin')
def admin_trap():
    return "Página no encontrada", 404

@app.route('/acceso-control', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == ADMIN_USER and password == ADMIN_PASS:
            session['logueado'] = True
            return redirect(ADMIN_ROUTE)
        else:
            error = "Usuario o contraseña incorrectos."
            
    return render_template('login.html', error=error)

@app.route(ADMIN_ROUTE)
@login_required
def admin_panel():
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    cursor.execute("SELECT * FROM citas ORDER BY id DESC")
    filas = cursor.fetchall()
    conexion.close()

    return render_template('admin.html', solicitudes=filas)

@app.route('/cambiar_estado/<int:id>')
@login_required
def cambiar_estado(id):
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    cursor.execute("SELECT estado FROM citas WHERE id = ?", (id,))
    cita = cursor.fetchone()
    
    if cita:
        nuevo_estado = 'Atendido' if cita['estado'] == 'Pendiente' else 'Pendiente'
        cursor.execute("UPDATE citas SET estado = ? WHERE id = ?", (nuevo_estado, id))
        conexion.commit()
        
    conexion.close()
    return redirect(ADMIN_ROUTE)

@app.route('/eliminar_cita/<int:id>')
@login_required
def eliminar_cita(id):
    conexion = obtener_conexion()
    cursor = conexion.cursor()
    cursor.execute("DELETE FROM citas WHERE id = ?", (id,))
    conexion.commit()
    conexion.close()
    
    return redirect(ADMIN_ROUTE)

@app.route('/logout')
def logout():
    session.pop('logueado', None)
    return redirect('/acceso-control')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
