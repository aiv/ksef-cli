"""
Klient API KSeF - uwierzytelnianie i pobieranie faktur
"""
import requests
import time
from typing import Optional, Dict, Any
from crypto import Crypto


class KSeFClient:
    """Klient systemu KSeF (środowisko produkcyjne)"""
    
    BASE_URL = "https://api.ksef.mf.gov.pl/v2"
    
    def __init__(self, ksef_token: str, context_nip: str):
        """
        Inicjalizacja klienta
        
        Args:
            ksef_token: Token KSeF
            context_nip: NIP kontekstu
        """
        self.ksef_token = ksef_token
        self.context_nip = context_nip
        self.crypto = Crypto()
        self.access_token: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
    
    def authenticate(self) -> bool:
        """
        Przeprowadza pełną procedurę uwierzytelniania
        
        Returns:
            True jeśli sukces
        """
        # Krok 1: Pobierz challenge
        challenge_data = self._get_challenge()
        challenge = challenge_data['challenge']
        timestamp_ms = challenge_data['timestampMs']
        
        # Krok 2: Zaszyfruj token
        encrypted_token = self.crypto.encrypt_token(self.ksef_token, timestamp_ms)
        
        # Krok 3: Wyślij żądanie uwierzytelnienia
        auth_response = self._submit_auth(encrypted_token, challenge)
        reference_number = auth_response['referenceNumber']
        auth_token = auth_response['authenticationToken']['token']
        
        # Krok 4: Sprawdź status (polling)
        self._wait_for_auth_completion(reference_number, auth_token)
        
        # Krok 5: Pobierz access token
        self._redeem_token(auth_token)
        
        return True
    
    def _get_challenge(self) -> Dict[str, Any]:
        """Pobiera auth challenge"""
        url = f"{self.BASE_URL}/auth/challenge"
        response = self.session.post(url)
        response.raise_for_status()
        return response.json()
    
    def _submit_auth(self, encrypted_token: str, challenge: str) -> Dict[str, Any]:
        """Wysyła żądanie uwierzytelnienia"""
        url = f"{self.BASE_URL}/auth/ksef-token"
        
        payload = {
            "challenge": challenge,
            "contextIdentifier": {
                "type": "nip",
                "value": self.context_nip
            },
            "encryptedToken": encrypted_token
        }
        
        response = self.session.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    
    def _wait_for_auth_completion(self, reference_number: str, auth_token: str, max_attempts: int = 10):
        """Czeka na zakończenie uwierzytelniania"""
        url = f"{self.BASE_URL}/auth/{reference_number}"
        headers = {'Authorization': f'Bearer {auth_token}'}
        
        for _ in range(max_attempts):
            response = self.session.get(url, headers=headers)
            response.raise_for_status()
            
            data = response.json()
            status_code = data.get('status', {}).get('code')
            
            # API zwraca kod 200 dla sukcesu
            if status_code == 200:
                return
            elif status_code >= 400:
                description = data.get('status', {}).get('description', 'Unknown error')
                raise Exception(f"Uwierzytelnianie nie powiodło się: {description}")
            
            time.sleep(2)
        
        raise Exception("Timeout podczas oczekiwania na uwierzytelnienie")
    
    def _redeem_token(self, auth_token: str):
        """Pobiera access token"""
        url = f"{self.BASE_URL}/auth/token/redeem"
        headers = {'Authorization': f'Bearer {auth_token}'}
        
        response = self.session.post(url, headers=headers)
        response.raise_for_status()
        
        data = response.json()
        self.access_token = data['accessToken']['token']
    
    def export_invoices(self, 
                       subject_type: str,
                       date_from: str,
                       date_to: Optional[str] = None,
                       encryption_key: bytes = None,
                       encryption_iv: bytes = None) -> Dict[str, Any]:
        """
        Inicjuje eksport faktur
        
        Args:
            subject_type: 'Subject1', 'Subject2', 'Subject3'
            date_from: Data od (ISO 8601)
            date_to: Data do (opcjonalne, ISO 8601)
            encryption_key: Klucz AES-256 (32 bajty)
            encryption_iv: IV dla AES (16 bajtów)
            
        Returns:
            Odpowiedź z API z referenceNumber
        """
        url = f"{self.BASE_URL}/invoices/exports"
        
        if not self.access_token:
            raise Exception("Brak tokena dostępowego - najpierw uwierzytelnij się")
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'X-KSeF-Feature': 'include-metadata'
        }
        
        # Generuj klucz i IV jeśli nie podano
        import os
        if encryption_key is None:
            encryption_key = os.urandom(32)
        if encryption_iv is None:
            encryption_iv = os.urandom(16)
        
        # Zaszyfruj klucz symetryczny kluczem publicznym
        encrypted_symmetric_key = self.crypto.encrypt_symmetric_key(encryption_key)
        
        # Przygotuj dane szyfrowania - API wymaga innych nazw pól
        import base64
        encryption_info = {
            "encryptedSymmetricKey": encrypted_symmetric_key,
            "initializationVector": base64.b64encode(encryption_iv).decode('utf-8'),
            "encryptionScheme": "AES-256-CBC"
        }
        
        # Przygotuj filtry
        filters = {
            "subjectType": subject_type,
            "dateRange": {
                "dateType": "PermanentStorage",
                "from": date_from,
                "restrictToPermanentStorageHwmDate": True
            }
        }
        
        if date_to:
            filters["dateRange"]["to"] = date_to
        
        payload = {
            "filters": filters,
            "encryption": encryption_info
        }
        
        response = self.session.post(url, json=payload, headers=headers)
        response.raise_for_status()
        
        # Przechowaj klucz i IV dla późniejszego deszyfrowania
        data = response.json()
        data['_encryption_key'] = encryption_key
        data['_encryption_iv'] = encryption_iv
        
        return data
    
    def get_export_status(self, reference_number: str) -> Dict[str, Any]:
        """
        Sprawdza status eksportu
        
        Args:
            reference_number: Numer referencyjny eksportu
            
        Returns:
            Status eksportu
        """
        url = f"{self.BASE_URL}/invoices/exports/{reference_number}"
        
        if not self.access_token:
            raise Exception("Brak tokena dostępowego")
        
        headers = {'Authorization': f'Bearer {self.access_token}'}
        
        response = self.session.get(url, headers=headers)
        response.raise_for_status()
        
        return response.json()
    
    def download_package_part(self, part_url: str) -> bytes:
        """
        Pobiera część paczki eksportu
        
        Args:
            part_url: URL części paczki (signed URL z Azure Storage)
            
        Returns:
            Surowe bajty zaszyfrowanej części
        """
        # Signed URL nie wymaga tokena Authorization
        response = self.session.get(part_url)
        response.raise_for_status()
        
        return response.content
