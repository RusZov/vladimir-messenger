"""
ble_mesh.py — BLE Mesh модуль для сверхближней связи

Использует Bluetooth Low Energy (BLE) для связи на расстоянии до 10 метров.
Поддерживает mesh-ретрансляцию через промежуточные узлы.

Примечание: Этот модуль опционален и требует Bluetooth-адаптер.
"""

import asyncio
import json
import time
import uuid
from typing import Optional, Callable, Dict, List
from dataclasses import dataclass


# UUID для сервиса Владимира (валидный 128-bit UUID)
VLADIMIR_SERVICE_UUID = "0000564c-0000-1000-8000-00805f9b34fb"  # VLAD в hex: 564C
VLADIMIR_CHAR_TX_UUID = "00005654-0000-1000-8000-00805f9b34fb"  # VLTx
VLADIMIR_CHAR_RX_UUID = "00005652-0000-1000-8000-00805f9b34fb"  # VLRx


@dataclass
class BLEPeer:
    """Информация о BLE пире"""
    device_id: str
    address: str
    rssi: int
    last_seen: float
    is_relay: bool = False


class BLEMesh:
    """Управление BLE mesh-сетью"""
    
    def __init__(self, node_id: str, public_key: str):
        self.node_id = node_id
        self.public_key = public_key
        
        # Состояние
        self.running = False
        self.peers: Dict[str, BLEPeer] = {}
        
        # BLE объекты
        self.bleak_client = None
        self.advertisement_started = False
        
        # Callbacks
        self.on_message_received: Optional[Callable] = None
        self.on_peer_discovered: Optional[Callable] = None
        
        # Mesh ретрансляция
        self.relay_messages: Dict[str, List[Dict]] = {}
        self.message_ttl = 300  # 5 минут
        self.max_hops = 3  # Максимальное количество прыжков
        
        # Очередь сообщений
        self.message_queue: asyncio.Queue = asyncio.Queue()
    
    async def start(self):
        """Запустить BLE mesh (асинхронно)"""
        try:
            from bleak import BleakScanner, BleakServer
            
            self.running = True
            
            # Запускаем сканирование в фоне
            asyncio.create_task(self._scan_loop())
            
            # Запускаем сервер для приёма соединений
            asyncio.create_task(self._server_loop())
            
            print("BLE mesh started")
            
        except ImportError:
            print("Bleak library not available, BLE disabled")
        except Exception as e:
            print(f"Failed to start BLE mesh: {e}")
    
    async def stop(self):
        """Остановить BLE mesh"""
        self.running = False
    
    async def _scan_loop(self):
        """Периодическое сканирование BLE устройств"""
        from bleak import BleakScanner
        
        while self.running:
            try:
                devices = await BleakScanner.discover(timeout=2.0, return_adv=True)
                
                for device, adv_data in devices.values():
                    # Проверяем наш сервис в advertisement data
                    if VLADIMIR_SERVICE_UUID in adv_data.service_uuids:
                        await self._handle_discovered_device(device, adv_data.rssi)
                
                await asyncio.sleep(3)  # Пауза между сканированиями
                
            except Exception as e:
                print(f"BLE scan error: {e}")
                await asyncio.sleep(5)
    
    async def _handle_discovered_device(self, device, rssi: int):
        """Обработать обнаруженное BLE устройство"""
        device_id = device.address
        
        # Создаём или обновляем информацию о пире
        peer = BLEPeer(
            device_id=device_id,
            address=device.address,
            rssi=rssi,
            last_seen=time.time()
        )
        
        is_new = device_id not in self.peers
        self.peers[device_id] = peer
        
        if is_new and self.on_peer_discovered:
            self.on_peer_discovered(peer)
        
        print(f"BLE peer discovered: {device_id} (RSSI: {rssi})")
    
    async def _server_loop(self):
        """Сервер для приёма BLE соединений"""
        # В полной реализации здесь будет BleakServer
        # Для прототипа симулируем приём сообщений
        pass
    
    async def send_message(self, peer_id: str, message: dict, hops: int = 0) -> bool:
        """
        Отправить сообщение через BLE
        
        Args:
            peer_id: Идентификатор получателя
            message: Сообщение
            hops: Количество уже сделанных прыжков
            
        Returns:
            True если отправлено успешно
        """
        if hops >= self.max_hops:
            print(f"Message TTL exceeded for {peer_id}")
            return False
        
        if peer_id in self.peers:
            # Прямая отправка
            return await self._send_direct(peer_id, message)
        else:
            # Ретрансляция через промежуточные узлы
            return await self._relay_message(peer_id, message, hops)
    
    async def _send_direct(self, peer_id: str, message: dict) -> bool:
        """Отправить сообщение напрямую"""
        try:
            from bleak import BleakClient
            
            peer = self.peers.get(peer_id)
            if not peer:
                return False
            
            # Подключаемся к устройству
            async with BleakClient(peer.address) as client:
                # Серализуем сообщение
                message['sender_id'] = self.node_id
                message['sender_public_key'] = self.public_key
                message['timestamp'] = time.time()
                message['hops'] = 0
                
                data = json.dumps(message).encode('utf-8')
                
                # Отправляем через characteristic
                await client.write_gatt_char(VLADIMIR_CHAR_TX_UUID, data)
                
                return True
                
        except Exception as e:
            print(f"BLE send error: {e}")
            return False
    
    async def _relay_message(self, peer_id: str, message: dict, hops: int) -> bool:
        """Ретранслировать сообщение через промежуточные узлы"""
        # Сохраняем сообщение для последующей ретрансляции
        if peer_id not in self.relay_messages:
            self.relay_messages[peer_id] = []
        
        message['queued_at'] = time.time()
        message['hops'] = hops + 1
        self.relay_messages[peer_id].append(message)
        
        # Очищаем старые сообщения
        expiry_time = time.time() - self.message_ttl
        self.relay_messages[peer_id] = [
            m for m in self.relay_messages[peer_id]
            if m.get('queued_at', 0) > expiry_time
        ]
        
        # Пытаемся отправить через доступные релеи
        for relay_peer in self.peers.values():
            if relay_peer.is_relay:
                relay_message = message.copy()
                relay_message['relay_for'] = peer_id
                
                if await self._send_direct(relay_peer.device_id, relay_message):
                    return True
        
        return False
    
    def get_mode_name(self) -> str:
        """Получить название режима"""
        return "BLE-mesh" if self.peers else "BLE (нет пиров)"
    
    def get_peers_list(self) -> List[Dict]:
        """Получить список BLE пиров"""
        return [
            {
                'peer_id': p.device_id,
                'address': p.address,
                'rssi': p.rssi,
                'last_seen': p.last_seen
            }
            for p in self.peers.values()
        ]


# Глобальный экземпляр (будет инициализирован при необходимости)
ble_mesh: Optional[BLEMesh] = None
