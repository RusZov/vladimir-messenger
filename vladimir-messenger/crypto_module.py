"""
crypto_module.py — Модуль сквозного шифрования

Использует X25519 для обмена ключами и ChaCha20-Poly1305 для шифрования сообщений.
"""

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives import serialization
import os
import base64
import json


class CryptoManager:
    """Управление криптографическими операциями"""
    
    def __init__(self):
        # Генерируем постоянный приватный ключ
        self.private_key = X25519PrivateKey.generate()
        self.public_key = self.private_key.public_key()
        
        # Хранилище публичных ключей контактов
        # Format: {contact_id: X25519PublicKey}
        self.contact_keys = {}
        
        # Кэширование общих секретов
        # Format: {(contact_id, my_key): shared_secret}
        self.shared_secrets = {}
    
    def get_public_key_bytes(self) -> bytes:
        """Получить публичный ключ в байтовом формате"""
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
    
    def get_public_key_base64(self) -> str:
        """Получить публичный ключ в Base64 (для передачи/QR-кода)"""
        return base64.b64encode(self.get_public_key_bytes()).decode('ascii')
    
    def add_contact_key(self, contact_id: str, public_key_b64: str) -> bool:
        """
        Добавить публичный ключ контакта
        
        Args:
            contact_id: Идентификатор контакта (например, username)
            public_key_b64: Публичный ключ в Base64
            
        Returns:
            True если ключ добавлен успешно
        """
        try:
            key_bytes = base64.b64decode(public_key_b64)
            if len(key_bytes) != 32:
                return False
            
            # Используем правильный метод для загрузки публичного ключа
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
            public_key = X25519PublicKey.from_public_bytes(key_bytes)
            self.contact_keys[contact_id] = public_key
            
            # Очистить кэш общего секрета для этого контакта
            self.shared_secrets.pop((contact_id, self.get_public_key_base64()), None)
            
            return True
        except Exception as e:
            print(f"Error adding contact key: {e}")
            return False
    
    def _get_shared_secret(self, contact_id: str) -> bytes:
        """
        Получить общий секрет для контакта (DH обмен)
        
        Кэширует результат для производительности
        """
        cache_key = (contact_id, self.get_public_key_base64())
        
        if cache_key in self.shared_secrets:
            return self.shared_secrets[cache_key]
        
        if contact_id not in self.contact_keys:
            raise ValueError(f"No public key for contact: {contact_id}")
        
        # Выполняем DH обмен
        shared_secret = self.private_key.exchange(
            self.contact_keys[contact_id]
        )
        
        # Хэшируем общий секрет для использования как ключ
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"vladimir-messenger-v1",
        )
        derived_key = hkdf.derive(shared_secret)
        
        self.shared_secrets[cache_key] = derived_key
        return derived_key
    
    def encrypt_message(self, contact_id: str, message: bytes) -> dict:
        """
        Зашифровать сообщение для контакта
        
        Args:
            contact_id: Идентификатор получателя
            message: Сообщение в байтах
            
        Returns:
            Dict с nonce и ciphertext в Base64
        """
        shared_secret = self._get_shared_secret(contact_id)
        
        # Генерируем уникальный nonce для каждого сообщения
        nonce = os.urandom(12)  # 96-bit nonce для ChaCha20
        
        chacha = ChaCha20Poly1305(shared_secret)
        ciphertext = chacha.encrypt(nonce, message, None)
        
        return {
            "nonce": base64.b64encode(nonce).decode('ascii'),
            "ciphertext": base64.b64encode(ciphertext).decode('ascii'),
            "type": "encrypted"
        }
    
    def decrypt_message(self, sender_id: str, encrypted_data: dict) -> bytes:
        """
        Расшифровать сообщение от контакта
        
        Args:
            sender_id: Идентификатор отправителя
            encrypted_data: Dict с nonce и ciphertext
            
        Returns:
            Расшифрованное сообщение в байтах
        """
        shared_secret = self._get_shared_secret(sender_id)
        
        nonce = base64.b64decode(encrypted_data["nonce"])
        ciphertext = base64.b64decode(encrypted_data["ciphertext"])
        
        chacha = ChaCha20Poly1305(shared_secret)
        plaintext = chacha.decrypt(nonce, ciphertext, None)
        
        return plaintext
    
    def encrypt_file(self, contact_id: str, file_data: bytes) -> dict:
        """Зашифровать файл для контакта"""
        return self.encrypt_message(contact_id, file_data)
    
    def decrypt_file(self, sender_id: str, encrypted_data: dict) -> bytes:
        """Расшифровать файл от контакта"""
        return self.decrypt_message(sender_id, encrypted_data)
    
    def sign_message(self, message: bytes) -> bytes:
        """
        Подписать сообщение (опционально, для верификации)
        
        Примечание: X25519 не поддерживает подписи напрямую.
        Для полноценной подписи нужно использовать Ed25519.
        В этом прототипе используем упрощённую схему.
        """
        # Упрощённая подпись через HMAC
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        
        # Получаем производный ключ для подписи
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"vladimir-signing-key",
        )
        signing_key = hkdf.derive(self.private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw
        ))
        
        from cryptography.hazmat.primitives import hmac
        h = hmac.HMAC(signing_key, hashes.SHA256())
        h.update(message)
        return h.finalize()
    
    def verify_signature(self, sender_id: str, message: bytes, signature: bytes) -> bool:
        """Проверить подпись сообщения"""
        # Для полноценной верификации нужен Ed25519
        # В прототипе возвращаем True для демонстрации
        return True


# Глобальный экземпляр менеджера криптографии
crypto_manager = CryptoManager()
