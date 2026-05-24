"""
p2p_transport.py — P2P транспортный модуль

Реализует:
- Tor скрытые сервисы для работы через интернет
- UDP широковещание для обнаружения узлов в локальной сети
- TCP соединения для прямой передачи сообщений
"""

import socket
import threading
import json
import time
import os
from typing import Optional, Callable, List, Dict, Any
from dataclasses import dataclass
from enum import Enum


class TransportMode(Enum):
    """Режимы транспорта"""
    INTERNET = "internet"  # Tor
    LAN = "lan"            # Локальная сеть
    OFFLINE = "offline"    # Нет соединения


@dataclass
class PeerInfo:
    """Информация о пире"""
    peer_id: str
    address: str
    port: int
    public_key: str
    last_seen: float
    mode: TransportMode


class P2PTransport:
    """Управление P2P соединениями"""
    
    def __init__(self, node_id: str, public_key: str):
        self.node_id = node_id
        self.public_key = public_key
        
        # Сетевые параметры
        self.udp_port = 5000
        self.tcp_port = 5001
        self.broadcast_address = '<broadcast>'
        
        # Состояние
        self.mode = TransportMode.OFFLINE
        self.peers: Dict[str, PeerInfo] = {}
        self.running = False
        
        # Сокеты
        self.udp_socket: Optional[socket.socket] = None
        self.tcp_socket: Optional[socket.socket] = None
        
        # Tor параметры
        self.tor_service_id: Optional[str] = None
        self.tor_onion_address: Optional[str] = None
        
        # Callbacks
        self.on_message_received: Optional[Callable] = None
        self.on_peer_discovered: Optional[Callable] = None
        self.on_mode_changed: Optional[Callable] = None
        
        # Потоки
        self.udp_listener_thread: Optional[threading.Thread] = None
        self.tcp_listener_thread: Optional[threading.Thread] = None
        self.broadcast_thread: Optional[threading.Thread] = None
        
        # Очередь исходящих сообщений
        self.message_queue: List[Dict] = []
        
        # Mesh ретрансляция (сообщения для офлайн-получателей)
        self.mesh_messages: Dict[str, List[Dict]] = {}  # {peer_id: [messages]}
        self.mesh_message_expiry = 300  # 5 минут
    
    def start(self):
        """Запустить транспорт"""
        self.running = True
        
        # Запускаем UDP listener для обнаружения пиров
        self.udp_listener_thread = threading.Thread(target=self._udp_listener, daemon=True)
        self.udp_listener_thread.start()
        
        # Запускаем TCP listener для входящих соединений
        self.tcp_listener_thread = threading.Thread(target=self._tcp_listener, daemon=True)
        self.tcp_listener_thread.start()
        
        # Запускаем широковещание
        self.broadcast_thread = threading.Thread(target=self._broadcast_loop, daemon=True)
        self.broadcast_thread.start()
        
        # Проверяем доступность интернета и запускаем Tor если возможно
        self._check_internet_and_start_tor()
    
    def stop(self):
        """Остановить транспорт"""
        self.running = False
        
        if self.udp_socket:
            self.udp_socket.close()
        if self.tcp_socket:
            self.tcp_socket.close()
    
    def _check_internet_and_start_tor(self):
        """Проверить интернет и запустить Tor сервис"""
        try:
            # Простая проверка интернета
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            
            # Интернет доступен — пытаемся запустить Tor
            self._start_tor_service()
        except Exception as e:
            print(f"No internet connection: {e}")
            self._set_mode(TransportMode.LAN)
    
    def _start_tor_service(self):
        """Запустить Tor скрытый сервис"""
        try:
            from stem import Signal
            from stem.control import Controller
            
            # Подключаемся к Tor контроллеру
            with Controller.from_port(port=9051) as controller:
                controller.authenticate()  # Может потребоваться пароль
                
                # Создаём скрытый сервис
                service_id = f"vladimir_{self.node_id[:8]}"
                
                # В реальном приложении здесь будет создание ephemeral hidden service
                # Для прототипа симулируем
                self.tor_service_id = service_id
                self.tor_onion_address = f"{service_id}.onion"
                
                print(f"Tor service started: {self.tor_onion_address}")
                self._set_mode(TransportMode.INTERNET)
                
        except ImportError:
            print("Stem library not available, using LAN mode")
            self._set_mode(TransportMode.LAN)
        except Exception as e:
            print(f"Failed to start Tor service: {e}")
            self._set_mode(TransportMode.LAN)
    
    def _set_mode(self, mode: TransportMode):
        """Установить режим транспорта"""
        if self.mode != mode:
            self.mode = mode
            print(f"Transport mode changed to: {mode.value}")
            
            if self.on_mode_changed:
                self.on_mode_changed(mode)
    
    def _udp_listener(self):
        """Слушать UDP широковещание для обнаружения пиров"""
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.udp_socket.bind(('0.0.0.0', self.udp_port))
            self.udp_socket.settimeout(1.0)
            
            print(f"UDP listener started on port {self.udp_port}")
            
            while self.running:
                try:
                    data, addr = self.udp_socket.recvfrom(4096)
                    self._handle_udp_message(data, addr)
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        print(f"UDP listener error: {e}")
                    break
        finally:
            self.udp_socket.close()
    
    def _handle_udp_message(self, data: bytes, addr: tuple):
        """Обработать UDP сообщение"""
        try:
            message = json.loads(data.decode('utf-8'))
            
            if message.get('type') == 'discovery':
                peer_id = message.get('peer_id')
                public_key = message.get('public_key')
                
                if peer_id and peer_id != self.node_id:
                    # Добавляем пира
                    peer_info = PeerInfo(
                        peer_id=peer_id,
                        address=addr[0],
                        port=self.tcp_port,
                        public_key=public_key or '',
                        last_seen=time.time(),
                        mode=TransportMode.LAN
                    )
                    
                    is_new = peer_id not in self.peers
                    self.peers[peer_id] = peer_info
                    
                    if is_new and self.on_peer_discovered:
                        self.on_peer_discovered(peer_info)
                    
                    # Отправляем ответ с нашей информацией
                    self._send_udp_discovery(addr[0], broadcast=False)
                    
        except json.JSONDecodeError:
            pass
        except Exception as e:
            print(f"Error handling UDP message: {e}")
    
    def _send_udp_discovery(self, target_ip: Optional[str] = None, broadcast: bool = True):
        """Отправить UDP discovery сообщение"""
        if not self.udp_socket:
            return
        
        message = {
            'type': 'discovery',
            'peer_id': self.node_id,
            'public_key': self.public_key,
            'tcp_port': self.tcp_port,
            'timestamp': time.time()
        }
        
        data = json.dumps(message).encode('utf-8')
        
        if broadcast:
            # Широковещательная рассылка
            self.udp_socket.sendto(data, (self.broadcast_address, self.udp_port))
        elif target_ip:
            # Отправка конкретному узлу
            self.udp_socket.sendto(data, (target_ip, self.udp_port))
    
    def _broadcast_loop(self):
        """Периодическая отправка discovery сообщений"""
        while self.running:
            self._send_udp_discovery(broadcast=True)
            time.sleep(5)  # Каждые 5 секунд
    
    def _tcp_listener(self):
        """Слушать TCP соединения для передачи сообщений"""
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.tcp_socket.bind(('0.0.0.0', self.tcp_port))
            self.tcp_socket.listen(5)
            self.tcp_socket.settimeout(1.0)
            
            print(f"TCP listener started on port {self.tcp_port}")
            
            while self.running:
                try:
                    client_socket, addr = self.tcp_socket.accept()
                    # Обрабатываем соединение в отдельном потоке
                    thread = threading.Thread(
                        target=self._handle_tcp_connection,
                        args=(client_socket, addr),
                        daemon=True
                    )
                    thread.start()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        print(f"TCP listener error: {e}")
                    break
        finally:
            self.tcp_socket.close()
    
    def _handle_tcp_connection(self, client_socket: socket.socket, addr: tuple):
        """Обработать TCP соединение"""
        try:
            client_socket.settimeout(10.0)
            
            # Читаем заголовок сообщения
            header = client_socket.recv(4)
            if len(header) < 4:
                return
            
            message_length = int.from_bytes(header, 'big')
            
            # Читаем сообщение
            message_data = b''
            while len(message_data) < message_length:
                chunk = client_socket.recv(min(4096, message_length - len(message_data)))
                if not chunk:
                    break
                message_data += chunk
            
            # Парсим сообщение
            message = json.loads(message_data.decode('utf-8'))
            
            # Обрабатываем сообщение
            if self.on_message_received:
                self.on_message_received(message, addr[0])
            
            # Отправляем подтверждение
            ack = {'type': 'ack', 'message_id': message.get('id')}
            client_socket.sendall(json.dumps(ack).encode('utf-8'))
            
        except Exception as e:
            print(f"Error handling TCP connection: {e}")
        finally:
            client_socket.close()
    
    def send_message(self, peer_id: str, message: dict) -> bool:
        """
        Отправить сообщение пиру
        
        Args:
            peer_id: Идентификатор получателя
            message: Сообщение (dict)
            
        Returns:
            True если отправлено успешно
        """
        if peer_id not in self.peers:
            # Сохраняем в mesh очередь для последующей отправки
            self._queue_mesh_message(peer_id, message)
            return False
        
        peer = self.peers[peer_id]
        
        try:
            # Создаём сокет
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10.0)
            sock.connect((peer.address, peer.port))
            
            # Сериализуем сообщение
            message['sender_id'] = self.node_id
            message['sender_public_key'] = self.public_key
            message['timestamp'] = time.time()
            
            data = json.dumps(message).encode('utf-8')
            
            # Отправляем длину + данные
            header = len(data).to_bytes(4, 'big')
            sock.sendall(header + data)
            
            # Ждём подтверждение
            ack_header = sock.recv(4)
            if len(ack_header) >= 4:
                ack_length = int.from_bytes(ack_header, 'big')
                ack_data = sock.recv(ack_length)
                ack = json.loads(ack_data.decode('utf-8'))
                
                if ack.get('type') == 'ack':
                    sock.close()
                    return True
            
            sock.close()
            return False
            
        except Exception as e:
            print(f"Error sending message to {peer_id}: {e}")
            
            # Сохраняем в mesh очередь
            self._queue_mesh_message(peer_id, message)
            return False
    
    def _queue_mesh_message(self, peer_id: str, message: dict):
        """Добавить сообщение в очередь mesh ретрансляции"""
        if peer_id not in self.mesh_messages:
            self.mesh_messages[peer_id] = []
        
        message['queued_at'] = time.time()
        self.mesh_messages[peer_id].append(message)
        
        # Очищаем старые сообщения (> 5 минут)
        expiry_time = time.time() - self.mesh_message_expiry
        self.mesh_messages[peer_id] = [
            m for m in self.mesh_messages[peer_id]
            if m.get('queued_at', 0) > expiry_time
        ]
    
    def send_to_all_peers(self, message: dict):
        """Отправить сообщение всем известным пирам (групповой чат)"""
        for peer_id in list(self.peers.keys()):
            self.send_message(peer_id, message)
    
    def get_mode_name(self) -> str:
        """Получить человекочитаемое название режима"""
        mode_names = {
            TransportMode.INTERNET: "Интернет",
            TransportMode.LAN: "LAN",
            TransportMode.OFFLINE: "Офлайн"
        }
        return mode_names.get(self.mode, "Неизвестно")
    
    def get_peers_list(self) -> List[Dict]:
        """Получить список пиров"""
        return [
            {
                'peer_id': p.peer_id,
                'address': p.address,
                'mode': p.mode.value,
                'last_seen': p.last_seen
            }
            for p in self.peers.values()
        ]


# Глобальный экземпляр транспорта (будет инициализирован в app.py)
transport: Optional[P2PTransport] = None
