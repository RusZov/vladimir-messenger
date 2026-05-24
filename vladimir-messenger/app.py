"""
app.py — Основное приложение Владимир Мессенджер

Flask веб-приложение с интеграцией P2P транспорта, шифрования и BLE.
"""

import os
import json
import time
import uuid
import base64
import threading
from flask import Flask, render_template, request, jsonify, Response
from werkzeug.utils import secure_filename

# Импорт наших модулей
from crypto_module import crypto_manager
from p2p_transport import P2PTransport, TransportMode
from ble_mesh import BLEMesh

# Инициализация Flask приложения
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB max file size

# Генерируем уникальный ID узла
NODE_ID = str(uuid.uuid4())[:8]

# Хранилище данных
contacts = {}  # {contact_id: {name, public_key, added_at}}
messages = []  # Список сообщений (локально)
files_dir = 'uploaded_files'

# Создаём директорию для файлов
os.makedirs(files_dir, exist_ok=True)

# Инициализация транспорта
transport = P2PTransport(NODE_ID, crypto_manager.get_public_key_base64())

# BLE mesh (опционально)
ble_mesh = None
ble_loop = None

# Флаг инициализации BLE
ble_initialized = False


def init_ble():
    """Инициализировать BLE mesh в отдельном потоке"""
    global ble_mesh, ble_initialized
    
    try:
        import asyncio
        
        async def run_ble():
            global ble_mesh
            ble_mesh = BLEMesh(NODE_ID, crypto_manager.get_public_key_base64())
            await ble_mesh.start()
            
            # Запускаем event loop
            while True:
                await asyncio.sleep(1)
        
        # Запускаем в отдельном потоке
        ble_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(ble_loop)
        ble_loop.run_until_complete(run_ble())
        
        ble_initialized = True
        
    except Exception as e:
        print(f"BLE initialization failed: {e}")
        ble_initialized = False


# Запускаем BLE в фоне
ble_thread = threading.Thread(target=init_ble, daemon=True)
ble_thread.start()


def on_message_received(message: dict, sender_address: str):
    """Обработчик полученных сообщений"""
    try:
        sender_id = message.get('sender_id')
        sender_public_key = message.get('sender_public_key')
        
        # Добавляем публичный ключ отправителя если ещё нет
        if sender_id and sender_public_key and sender_id not in crypto_manager.contact_keys:
            crypto_manager.add_contact_key(sender_id, sender_public_key)
        
        # Расшифровываем сообщение если зашифровано
        if message.get('type') == 'encrypted':
            try:
                decrypted = crypto_manager.decrypt_message(sender_id, message)
                message['content'] = decrypted.decode('utf-8')
                message['decrypted'] = True
            except Exception as e:
                print(f"Decryption error: {e}")
                message['content'] = '[Ошибка расшифровки]'
                message['decrypted'] = False
        
        # Сохраняем сообщение
        messages.append({
            'id': message.get('id', str(uuid.uuid4())),
            'sender_id': sender_id,
            'content': message.get('content'),
            'timestamp': message.get('timestamp', time.time()),
            'type': message.get('message_type', 'text'),
            'direction': 'incoming',
            'address': sender_address
        })
        
        print(f"Message received from {sender_id}: {message.get('content')}")
        
    except Exception as e:
        print(f"Error processing message: {e}")


def on_peer_discovered(peer_info):
    """Обработчик обнаружения нового пира"""
    print(f"Peer discovered: {peer_info.peer_id} at {peer_info.address}")
    
    # Если у пира есть публичный ключ, добавляем его как контакт
    if peer_info.public_key:
        contact_id = f"peer_{peer_info.peer_id}"
        if contact_id not in contacts:
            contacts[contact_id] = {
                'name': f"Peer {peer_info.peer_id[:6]}",
                'public_key': peer_info.public_key,
                'added_at': time.time(),
                'auto_discovered': True
            }


def on_mode_changed(mode: TransportMode):
    """Обработчик смены режима транспорта"""
    print(f"Mode changed to: {mode.value}")


# Регистрируем callback-и
transport.on_message_received = on_message_received
transport.on_peer_discovered = on_peer_discovered
transport.on_mode_changed = on_mode_changed

# Запускаем транспорт
transport.start()


@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html', 
                         node_id=NODE_ID,
                         public_key=crypto_manager.get_public_key_base64(),
                         mode=transport.get_mode_name())


@app.route('/api/status')
def get_status():
    """Получить статус приложения"""
    return jsonify({
        'node_id': NODE_ID,
        'public_key': crypto_manager.get_public_key_base64(),
        'mode': transport.get_mode_name(),
        'mode_raw': transport.mode.value,
        'peers_count': len(transport.peers),
        'contacts_count': len(contacts),
        'messages_count': len(messages),
        'ble_enabled': ble_initialized
    })


@app.route('/api/contacts', methods=['GET'])
def get_contacts():
    """Получить список контактов"""
    contact_list = []
    for contact_id, data in contacts.items():
        contact_list.append({
            'id': contact_id,
            'name': data['name'],
            'public_key': data['public_key'][:20] + '...' if len(data['public_key']) > 20 else data['public_key'],
            'added_at': data['added_at']
        })
    return jsonify(contact_list)


@app.route('/api/contacts', methods=['POST'])
def add_contact():
    """Добавить контакт"""
    data = request.json
    name = data.get('name')
    public_key = data.get('public_key')
    
    if not name or not public_key:
        return jsonify({'error': 'Name and public key required'}), 400
    
    # Проверяем формат публичного ключа
    try:
        key_bytes = base64.b64decode(public_key)
        if len(key_bytes) != 32:
            return jsonify({'error': 'Invalid public key length'}), 400
    except Exception:
        return jsonify({'error': 'Invalid public key format'}), 400
    
    # Добавляем ключ в крипто менеджер
    contact_id = f"contact_{name.lower().replace(' ', '_')}"
    
    if not crypto_manager.add_contact_key(contact_id, public_key):
        return jsonify({'error': 'Failed to add contact key'}), 400
    
    # Сохраняем контакт
    contacts[contact_id] = {
        'name': name,
        'public_key': public_key,
        'added_at': time.time()
    }
    
    return jsonify({'success': True, 'contact_id': contact_id})


@app.route('/api/contacts/<contact_id>', methods=['DELETE'])
def delete_contact(contact_id):
    """Удалить контакт"""
    if contact_id in contacts:
        del contacts[contact_id]
        return jsonify({'success': True})
    return jsonify({'error': 'Contact not found'}), 404


@app.route('/api/messages', methods=['GET'])
def get_messages():
    """Получить сообщения"""
    contact_id = request.args.get('contact_id')
    
    if contact_id:
        # Фильтруем сообщения по контакту
        filtered = [m for m in messages if m['sender_id'] == contact_id or 
                   (m['direction'] == 'outgoing' and m.get('recipient_id') == contact_id)]
        return jsonify(filtered)
    
    return jsonify(messages[-50:])  # Последние 50 сообщений


@app.route('/api/messages', methods=['POST'])
def send_message():
    """Отправить сообщение"""
    data = request.json
    recipient_id = data.get('recipient_id')
    content = data.get('content')
    message_type = data.get('type', 'text')
    
    if not recipient_id or not content:
        return jsonify({'error': 'Recipient and content required'}), 400
    
    # Шифруем сообщение
    try:
        encrypted = crypto_manager.encrypt_message(recipient_id, content.encode('utf-8'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    
    # Создаём сообщение
    message = {
        'id': str(uuid.uuid4()),
        'type': 'encrypted',
        'message_type': message_type,
        **encrypted
    }
    
    # Отправляем через транспорт
    sent = transport.send_message(recipient_id, message)
    
    # Сохраняем локально
    messages.append({
        'id': message['id'],
        'sender_id': NODE_ID,
        'recipient_id': recipient_id,
        'content': content,
        'timestamp': time.time(),
        'type': message_type,
        'direction': 'outgoing',
        'sent': sent
    })
    
    return jsonify({
        'success': sent,
        'message_id': message['id']
    })


@app.route('/api/messages/broadcast', methods=['POST'])
def broadcast_message():
    """Отправить сообщение всем пирам (групповой чат)"""
    data = request.json
    content = data.get('content')
    
    if not content:
        return jsonify({'error': 'Content required'}), 400
    
    # Шифруем для каждого контакта
    for contact_id in contacts.keys():
        try:
            encrypted = crypto_manager.encrypt_message(contact_id, content.encode('utf-8'))
            message = {
                'id': str(uuid.uuid4()),
                'type': 'encrypted',
                'message_type': 'broadcast',
                **encrypted
            }
            transport.send_message(contact_id, message)
        except Exception as e:
            print(f"Failed to send to {contact_id}: {e}")
    
    # Сохраняем локально
    messages.append({
        'id': str(uuid.uuid4()),
        'sender_id': NODE_ID,
        'content': content,
        'timestamp': time.time(),
        'type': 'broadcast',
        'direction': 'outgoing',
        'broadcast': True
    })
    
    return jsonify({'success': True})


@app.route('/api/files', methods=['POST'])
def send_file():
    """Отправить файл"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    recipient_id = request.form.get('recipient_id')
    if not recipient_id:
        return jsonify({'error': 'Recipient required'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    # Сохраняем файл временно
    filename = secure_filename(file.filename)
    filepath = os.path.join(files_dir, f"{uuid.uuid4()}_{filename}")
    file.save(filepath)
    
    try:
        # Читаем файл и шифруем
        with open(filepath, 'rb') as f:
            file_data = f.read()
        
        encrypted = crypto_manager.encrypt_file(recipient_id, file_data)
        
        # Создаём сообщение с файлом
        message = {
            'id': str(uuid.uuid4()),
            'type': 'encrypted_file',
            'filename': filename,
            'filesize': len(file_data),
            **encrypted
        }
        
        # Отправляем
        sent = transport.send_message(recipient_id, message)
        
        # Сохраняем запись о сообщении
        messages.append({
            'id': message['id'],
            'sender_id': NODE_ID,
            'recipient_id': recipient_id,
            'content': f'[Файл: {filename}]',
            'filename': filename,
            'filesize': len(file_data),
            'timestamp': time.time(),
            'type': 'file',
            'direction': 'outgoing',
            'sent': sent
        })
        
        return jsonify({'success': sent})
        
    finally:
        # Удаляем временный файл
        if os.path.exists(filepath):
            os.remove(filepath)


@app.route('/api/peers', methods=['GET'])
def get_peers():
    """Получить список обнаруженных пиров"""
    peers = transport.get_peers_list()
    
    # Добавляем BLE пиры если доступны
    if ble_initialized and ble_mesh:
        ble_peers = ble_mesh.get_peers_list()
        for peer in ble_peers:
            peer['mode'] = 'ble'
            peers.append(peer)
    
    return jsonify(peers)


@app.route('/api/scan', methods=['POST'])
def scan_peers():
    """Запустить сканирование пиров"""
    # Транспорт уже сканирует автоматически
    # Этот эндпоинт для принудительного обновления
    return jsonify({'success': True, 'message': 'Scan initiated'})


if __name__ == '__main__':
    print("=" * 60)
    print("ВЛАДИМИР МЕССЕНДЖЕР — Прототип")
    print("=" * 60)
    print(f"Node ID: {NODE_ID}")
    print(f"Public Key: {crypto_manager.get_public_key_base64()}")
    print(f"Web Interface: http://localhost:5000")
    print("=" * 60)
    print("\nЗапуск сервера...\n")
    
    # Запускаем Flask
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
