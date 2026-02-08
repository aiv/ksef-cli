#!/usr/bin/env python3
"""
Narzędzie do przyrostowego pobierania faktur z KSeF
Zapisuje faktury w folderze faktury/ i zwraca JSON z podsumowaniem
"""
import os
import sys
import json
import time
import argparse
import zipfile
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set, Optional
from dotenv import load_dotenv

from client import KSeFClient
from crypto import Crypto


# Ścieżki
BASE_DIR = Path(__file__).parent
FAKTURY_DIR = BASE_DIR / "faktury"
STATE_FILE = BASE_DIR / ".ksef_state.json"


class InvoiceFetcher:
    """Klasa obsługująca przyrostowe pobieranie faktur"""
    
    # Typy podmiotów do pobierania
    SUBJECT_TYPES = ['Subject1', 'Subject2', 'Subject3']
    
    def __init__(self, client: KSeFClient, output_format: str = 'json'):
        self.client = client
        self.output_format = output_format
        self.crypto = Crypto()
        
        # Twórz katalog na faktury jeśli nie istnieje
        FAKTURY_DIR.mkdir(exist_ok=True)
        
        # Załaduj stan ostatniego pobierania
        self.state = self._load_state()
        
        # Zbiór pobranych faktur (deduplikacja)
        self.downloaded_invoices: Set[str] = set()
        
        # Nowe faktury w tym przebiegu
        self.new_invoices: List[Dict] = []
    
    def _load_state(self) -> Dict:
        """Ładuje stan ostatniego pobierania"""
        if STATE_FILE.exists():
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        return {}
    
    def _save_state(self):
        """Zapisuje stan ostatniego pobierania"""
        with open(STATE_FILE, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def fetch_invoices(self):
        """Główna metoda pobierająca faktury"""
        # Uwierzytelnij się
        self.client.authenticate()
        
        # Pobierz faktury dla każdego typu podmiotu
        for subject_type in self.SUBJECT_TYPES:
            self._fetch_for_subject_type(subject_type)
        
        # Zapisz stan
        self._save_state()
        
        # Zwróć wynik
        return self._format_output()
    
    def _fetch_for_subject_type(self, subject_type: str):
        """Pobiera faktury dla danego typu podmiotu"""
        # Określ punkt startowy
        state_key = f"continuation_point_{subject_type}"
        date_from = self.state.get(state_key)
        
        if not date_from:
            # Pierwszy raz - pobierz od początku miesiąca
            now = datetime.now(timezone.utc)
            date_from = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        
        # Inicjuj eksport (bez date_to - system sam określi zakres)
        export_response = self.client.export_invoices(
            subject_type=subject_type,
            date_from=date_from
        )
        
        reference_number = export_response['referenceNumber']
        encryption_key = export_response['_encryption_key']
        encryption_iv = export_response['_encryption_iv']
        
        # Poczekaj na zakończenie eksportu
        status = self._wait_for_export_completion(reference_number)
        
        if status.get('package'):
            # Pobierz i przetwórz paczkę
            package = status['package']
            self._process_package(package, encryption_key, encryption_iv)
            
            # Aktualizuj punkt kontynuacji
            self._update_continuation_point(subject_type, package)
    
    def _wait_for_export_completion(self, reference_number: str, max_attempts: int = 60) -> Dict:
        """Czeka na zakończenie eksportu"""
        for _ in range(max_attempts):
            status = self.client.get_export_status(reference_number)
            
            status_code = status.get('status', {}).get('code')
            
            # API zwraca kod 200 dla sukcesu
            if status_code == 200:
                return status
            elif status_code >= 400:
                description = status.get('status', {}).get('description', 'Unknown error')
                raise Exception(f"Eksport nie powiódł się: {description}")
            
            time.sleep(5)
        
        raise Exception("Timeout podczas oczekiwania na eksport")
    
    def _process_package(self, package: Dict, encryption_key: bytes, encryption_iv: bytes):
        """Przetwarza paczkę z fakturami"""
        parts = package.get('parts', [])
        
        if not parts:
            return
        
        # Pobierz i połącz części
        encrypted_data = BytesIO()
        for part in parts:
            part_url = part['url']
            part_data = self.client.download_package_part(part_url)
            encrypted_data.write(part_data)
        
        # Odszyfruj
        encrypted_data.seek(0)
        decrypted_data = self.crypto.decrypt_aes(
            encrypted_data.read(),
            encryption_key,
            encryption_iv
        )
        
        # Rozpakuj ZIP
        with zipfile.ZipFile(BytesIO(decrypted_data)) as zf:
            # Odczytaj metadane
            metadata = None
            if '_metadata.json' in zf.namelist():
                with zf.open('_metadata.json') as f:
                    metadata = json.load(f)
            
            # Przetwórz faktury
            for filename in zf.namelist():
                if filename.endswith('.xml'):
                    self._save_invoice(zf, filename, metadata)
    
    def _save_invoice(self, zf: zipfile.ZipFile, filename: str, metadata: Optional[Dict]):
        """Zapisuje fakturę do pliku"""
        # Wyciągnij numer KSeF z metadanych
        ksef_number = None
        if metadata and 'invoices' in metadata:
            # Znajdź fakturę po nazwie pliku
            for inv in metadata['invoices']:
                inv_filename = f"{inv['ksefNumber']}.xml"
                if inv_filename == filename:
                    ksef_number = inv['ksefNumber']
                    break
        
        # Jeśli nie ma w metadanych, spróbuj wyciągnąć z nazwy pliku
        if not ksef_number:
            ksef_number = filename.replace('.xml', '')
        
        # Sprawdź deduplikację
        if ksef_number in self.downloaded_invoices:
            return
        
        # Sprawdź czy już istnieje na dysku
        invoice_path = FAKTURY_DIR / filename
        if invoice_path.exists():
            self.downloaded_invoices.add(ksef_number)
            return
        
        # Zapisz fakturę
        with zf.open(filename) as f:
            invoice_content = f.read()
        
        with open(invoice_path, 'wb') as f:
            f.write(invoice_content)
        
        # Dodaj do listy nowych
        self.downloaded_invoices.add(ksef_number)
        self.new_invoices.append({
            'ksefNumber': ksef_number,
            'filename': filename
        })
    
    def _update_continuation_point(self, subject_type: str, package: Dict):
        """Aktualizuje punkt kontynuacji dla typu podmiotu"""
        state_key = f"continuation_point_{subject_type}"
        
        # Zgodnie z dokumentacją: jeśli IsTruncated=true, używamy LastPermanentStorageDate
        # W przeciwnym razie PermanentStorageHwmDate
        if package.get('isTruncated'):
            last_date = package.get('lastPermanentStorageDate')
            if last_date:
                self.state[state_key] = last_date
        else:
            hwm_date = package.get('permanentStorageHwmDate')
            if hwm_date:
                self.state[state_key] = hwm_date
    
    def _format_output(self) -> str:
        """Formatuje output zgodnie z wybranym formatem"""
        result = {
            'count': len(self.new_invoices),
            'invoices': self.new_invoices
        }
        
        if self.output_format == 'json':
            return json.dumps(result, indent=2, ensure_ascii=False)
        else:
            # Format tekstowy
            lines = [
                f"Pobrano {result['count']} nowych faktur:",
                ""
            ]
            for inv in result['invoices']:
                lines.append(f"  - {inv['ksefNumber']} ({inv['filename']})")
            
            return "\n".join(lines)


def main():
    """Główna funkcja programu"""
    parser = argparse.ArgumentParser(
        description='Narzędzie do przyrostowego pobierania faktur z KSeF'
    )
    parser.add_argument(
        '--format',
        choices=['json', 'text'],
        default='json',
        help='Format outputu (domyślnie: json)'
    )
    parser.add_argument(
        '--token',
        help='Token KSeF (nadpisuje KSEF_TOKEN z .env)'
    )
    parser.add_argument(
        '--nip',
        help='NIP kontekstu (nadpisuje CONTEXT_NIP z .env)'
    )

    args = parser.parse_args()

    # Załaduj konfigurację
    load_dotenv()

    ksef_token = args.token or os.getenv('KSEF_TOKEN')
    context_nip = args.nip or os.getenv('CONTEXT_NIP')
    
    if not ksef_token or not context_nip:
        print(json.dumps({
            'error': 'Brak konfiguracji - ustaw KSEF_TOKEN i CONTEXT_NIP w pliku .env'
        }), file=sys.stderr)
        sys.exit(1)
    
    try:
        # Utwórz klienta
        client = KSeFClient(ksef_token, context_nip)
        
        # Pobierz faktury
        fetcher = InvoiceFetcher(client, args.format)
        output = fetcher.fetch_invoices()
        
        # Wyświetl wynik
        print(output)
        
    except Exception as e:
        error_output = {
            'error': str(e),
            'count': 0,
            'invoices': []
        }
        
        if args.format == 'json':
            print(json.dumps(error_output, indent=2), file=sys.stderr)
        else:
            print(f"BŁĄD: {e}", file=sys.stderr)
        
        sys.exit(1)


if __name__ == '__main__':
    main()
