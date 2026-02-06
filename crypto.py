"""
Moduł kryptograficzny do szyfrowania tokenów KSeF oraz deszyfrowania faktur
"""
import base64
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography import x509


class Crypto:
    """Obsługa operacji kryptograficznych dla KSeF"""
    
    def __init__(self):
        """Inicjalizacja - pobiera klucze publiczne z API produkcyjnego"""
        self._fetch_public_keys()
    
    def _fetch_public_keys(self):
        """Pobiera klucze publiczne z API KSeF (produkcja)"""
        url = "https://api.ksef.mf.gov.pl/v2/security/public-key-certificates"
        
        response = requests.get(url)
        response.raise_for_status()
        
        certificates = response.json()
        
        # Znajdź certyfikaty do szyfrowania
        for cert_info in certificates:
            usage = cert_info.get('usage', [])
            certificate_b64 = cert_info['certificate']
            
            if 'KsefTokenEncryption' in usage:
                self.token_public_key = self._load_public_key(certificate_b64)
            
            if 'SymmetricKeyEncryption' in usage:
                self.symmetric_key_public_key = self._load_public_key(certificate_b64)
        
        if not hasattr(self, 'token_public_key'):
            raise Exception("Nie znaleziono certyfikatu do szyfrowania tokenów KSeF")
        
        if not hasattr(self, 'symmetric_key_public_key'):
            raise Exception("Nie znaleziono certyfikatu do szyfrowania kluczy symetrycznych")
    
    def _load_public_key(self, certificate_b64: str):
        """Ładuje klucz publiczny z certyfikatu w formacie Base64"""
        cert_der = base64.b64decode(certificate_b64)
        cert = x509.load_der_x509_certificate(cert_der, default_backend())
        return cert.public_key()
    
    def encrypt_token(self, ksef_token: str, timestamp_ms: int) -> str:
        """
        Szyfruje token KSeF wraz z timestampem
        
        Args:
            ksef_token: Token KSeF
            timestamp_ms: Timestamp w milisekundach
            
        Returns:
            Zaszyfrowany token w Base64
        """
        token_with_timestamp = f"{ksef_token}|{timestamp_ms}"
        token_bytes = token_with_timestamp.encode('utf-8')
        
        encrypted = self.token_public_key.encrypt(
            token_bytes,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        
        return base64.b64encode(encrypted).decode('utf-8')
    
    def decrypt_aes(self, encrypted_data: bytes, key: bytes, iv: bytes) -> bytes:
        """
        Deszyfruje dane AES-256-CBC
        
        Args:
            encrypted_data: Zaszyfrowane dane
            key: Klucz AES (32 bajty)
            iv: Wektor inicjalizacji (16 bajtów)
            
        Returns:
            Odszyfrowane dane
        """
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        
        decrypted = decryptor.update(encrypted_data) + decryptor.finalize()
        
        # Usuń padding PKCS7
        padding_length = decrypted[-1]
        return decrypted[:-padding_length]
    
    def encrypt_symmetric_key(self, symmetric_key: bytes) -> str:
        """
        Szyfruje klucz symetryczny (AES) kluczem publicznym RSA
        
        Args:
            symmetric_key: Klucz AES do zaszyfrowania (32 bajty)
            
        Returns:
            Zaszyfrowany klucz w Base64
        """
        encrypted = self.symmetric_key_public_key.encrypt(
            symmetric_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        
        return base64.b64encode(encrypted).decode('utf-8')
