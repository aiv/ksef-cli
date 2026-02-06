# KSeF Invoice Fetcher

Minimalistyczne narzędzie do przyrostowego pobierania faktur z KSeF.

## Wymagania

- Python 3.8+
- Token KSeF i NIP kontekstu

## Instalacja

```bash
pip install -r requirements.txt
```

## Konfiguracja

Skopiuj plik `.env.example` do `.env` i uzupełnij:

```bash
cp .env.example .env
```

Edytuj `.env`:
```
KSEF_TOKEN=twój-token-ksef
CONTEXT_NIP=1234567890
```

## Użycie

### Format JSON (domyślny)
```bash
python fetch_invoices.py
```

Output:
```json
{
  "count": 5,
  "invoices": [
    {
      "ksefNumber": "1234567890-20240101-ABCD-01",
      "filename": "1234567890-20240101-ABCD-01.xml"
    },
    ...
  ]
}
```

### Format tekstowy
```bash
python fetch_invoices.py --format text
```

Output:
```
Pobrano 5 nowych faktur:

  - 1234567890-20240101-ABCD-01 (1234567890-20240101-ABCD-01.xml)
  - ...
```

## Jak działa

1. **Uwierzytelnianie** - używa tokena KSeF
2. **Przyrostowe pobieranie**)
   - Używa mechanizmu High Water Mark (HWM)
   - Pobiera faktury dla Subject1, Subject2, Subject3
   - Zapisuje punkt kontynuacji w `.ksef_state.json`
3. **Deduplikacja** - eliminuje duplikaty na podstawie numerów KSeF
4. **Zapis** - faktury XML zapisywane w `faktury/`

## Pliki

- `fetch_invoices.py` - główne narzędzie
- `client.py` - klient API KSeF
- `crypto.py` - moduł kryptograficzny
- `.ksef_state.json` - stan ostatniego pobierania (tworzony automatycznie)
- `faktury/` - katalog z pobranymi fakturami (tworzony automatycznie)
