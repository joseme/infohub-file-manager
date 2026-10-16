#!/usr/bin/env python3
"""
Importación de contactos ManyChat → ChatWoot (Fase 4 del plan de migración).

Lee un archivo JSON con contactos exportados de ManyChat (vía Google Sheets,
API o nodo Data Collection) y los crea en la API de ChatWoot:

    python scripts/import_manychat_to_chatwoot.py \
        --input contacts.json \
        --chatwoot-url https://chat.tudominio.com \
        --account-id 1 \
        --api-token $CHATWOOT_API_TOKEN

Formato de entrada: lista de contactos (o {"data": [...]} / {"contacts": [...]},
{"subscribers": [...]}) con claves tolerantes al export de ManyChat:

    [
      {
        "id": 12345,
        "first_name": "Ana",
        "last_name": "Pérez",
        "phone": "+54911223344",
        "email": "ana@ejemplo.com",
        "tags": ["vip", "mayorista"],
        "custom_fields": {"plan_anual": "Premium", "ciudad": "CDMX"}
      }
    ]

Comportamiento:
  - Dedupe por teléfono (fallback email) antes de crear; los duplicados
    fusionan labels, atributos y datos faltantes.
  - Consulta contactos existentes en ChatWoot por teléfono (endpoint search)
    antes de crear, para no generar duplicados en re-ejecuciones.
  - Crea labels y custom attribute definitions faltantes (tipo inferido).
  - Rate limit amable (default 5 req/s) con reintentos ante 429/5xx.
  - --dry-run: solo lecturas, ninguna escritura.
  - --report reporte.json: totales y errores para reintento.
  - --update-existing: además de crear, actualiza atributos/labels de
    contactos que ya existen en ChatWoot (default: saltarlos).

Exit codes: 0 OK · 1 import con fallos · 2 error de configuración/entrada.
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

DEFAULT_RATE = 5  # req/s, "rate-limit amable" según Fase 4 del plan
RETRYABLE_STATUS = (429, 500, 502, 503, 504)


class ChatwootAPIError(Exception):
    """Error de la API de ChatWoot tras agotar reintentos o respuesta inválida."""


# ---------------------------------------------------------------------------
# Normalización de datos
# ---------------------------------------------------------------------------

def slugify_label(tag):
    """Convierte un tag de ManyChat en un label válido de ChatWoot."""
    s = re.sub(r"[^a-z0-9]+", "-", str(tag).strip().lower()).strip("-")
    return s or None


def sanitize_attribute_key(key):
    """Convierte un nombre de custom field en un attribute_key válido."""
    s = re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")
    return s or "campo"


def normalize_phone(raw):
    """Normaliza a dígitos con '+' inicial si lo tenía. None si es inválido."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    digits = re.sub(r"\D", "", s)
    if len(digits) < 7:
        return None
    return ("+" + digits) if s.startswith("+") else digits


def normalize_contact(raw):
    """Mapea un contacto crudo de ManyChat al modelo de ChatWoot.

    Devuelve None si el contacto no tiene ningún identificador utilizable
    (teléfono, email o nombre).
    """
    if not isinstance(raw, dict):
        return None

    name = raw.get("name") or " ".join(
        part for part in (raw.get("first_name"), raw.get("last_name")) if part
    ).strip() or None
    phone = normalize_phone(raw.get("phone") or raw.get("phone_number"))
    email = (raw.get("email") or "").strip() or None

    tags = raw.get("tags", raw.get("labels", []))
    if isinstance(tags, str):
        tags = [t for t in re.split(r"[;,]", tags) if t.strip()]
    labels = sorted({slug for slug in (slugify_label(t) for t in tags or []) if slug})

    attrs_raw = raw.get("custom_fields") or raw.get("custom_attributes") or raw.get("fields") or {}
    attrs = {}
    if isinstance(attrs_raw, dict):
        for key, value in attrs_raw.items():
            skey = sanitize_attribute_key(key)
            if skey:
                attrs[skey] = value

    if not (phone or email or name):
        return None

    return {
        "identifier": str(raw["id"]) if raw.get("id") is not None else None,
        "name": name,
        "phone": phone,
        "email": email,
        "labels": labels,
        "custom_attributes": attrs,
    }


def _contact_keys(contact):
    """Claves de dedupe: teléfono (solo dígitos), email y nombre normalizado."""
    keys = []
    if contact["phone"]:
        keys.append("phone:" + re.sub(r"\D", "", contact["phone"]))
    if contact["email"]:
        keys.append("email:" + contact["email"].lower())
    if contact["name"]:
        keys.append("name:" + " ".join(contact["name"].strip().lower().split()))
    return keys


def _merge_into(base, extra):
    """Fusiona `extra` en `base`: el primero gana, el segundo completa."""
    base["labels"] = sorted(set(base["labels"]) | set(extra["labels"]))
    for attr, value in extra["custom_attributes"].items():
        if value not in (None, ""):
            base["custom_attributes"][attr] = value
    base["name"] = base["name"] or extra["name"]
    base["phone"] = base["phone"] or extra["phone"]
    base["email"] = base["email"] or extra["email"]
    base["identifier"] = base["identifier"] or extra["identifier"]


def dedupe_contacts(contacts):
    """Fusiona contactos que compartan cualquier clave (teléfono, email o nombre).

    El primero gana; los siguientes aportan labels (unión), atributos
    (los no vacíos pisan) y datos faltantes. Conserva el orden de aparición.
    """
    parent = list(range(len(contacts)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    key_to_index = {}
    for i, contact in enumerate(contacts):
        for key in _contact_keys(contact):
            if key in key_to_index:
                root, other = find(i), find(key_to_index[key])
                if root != other:
                    parent[max(root, other)] = min(root, other)
            else:
                key_to_index[key] = i

    groups = {}
    for i, contact in enumerate(contacts):
        groups.setdefault(find(i), []).append(contact)

    merged_list = []
    for members in groups.values():
        merged = members[0]
        for other in members[1:]:
            _merge_into(merged, other)
        merged_list.append(merged)
    return merged_list


def load_contacts(path):
    """Carga el JSON de export de ManyChat y devuelve las filas crudas."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("data") or data.get("contacts") or data.get("subscribers") or []
    return []


def prepare_contacts(rows):
    """Normaliza y deduplica las filas crudas.

    Devuelve (contactos listos, inválidos descartados, duplicados fusionados).
    """
    normalized = []
    invalid = 0
    for row in rows:
        contact = normalize_contact(row)
        if contact is None:
            invalid += 1
        else:
            normalized.append(contact)
    deduped = dedupe_contacts(normalized)
    return deduped, invalid, len(normalized) - len(deduped)


def infer_attribute_type(values):
    """Infiere el attribute_display_type de ChatWoot a partir de los valores."""
    values = [v for v in values if v is not None]
    if values and all(isinstance(v, bool) for v in values):
        return "checkbox"
    if values and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        return "number"
    return "text"


def extract_label_titles(value):
    """Extrae títulos de labels tolerando list[str], list[dict] o dict anidado."""
    if isinstance(value, dict):
        value = value.get("labels", [])
    titles = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                titles.append(item)
            elif isinstance(item, dict):
                title = item.get("title") or item.get("name")
                if title:
                    titles.append(title)
    return titles


# ---------------------------------------------------------------------------
# Cliente de la API de ChatWoot
# ---------------------------------------------------------------------------

class ChatwootClient:
    """Cliente mínimo de la API de ChatWoot con rate limit y reintentos."""

    def __init__(self, base_url, account_id, api_token, rate_per_sec=DEFAULT_RATE,
                 session=None, sleep_fn=time.sleep):
        self.base_url = base_url.rstrip("/")
        self.account_id = int(account_id)
        self.api_token = api_token
        self.min_interval = 1.0 / float(rate_per_sec)
        self.session = session or requests.Session()
        self._sleep = sleep_fn
        self._last_request_ts = 0.0

    # -- infraestructura ----------------------------------------------------

    def _throttle(self):
        wait = self._last_request_ts + self.min_interval - time.monotonic()
        if wait > 0:
            self._sleep(wait)
        self._last_request_ts = time.monotonic()

    def request(self, method, path, json_body=None, attempts=3):
        """Ejecuta un request con backoff ante 429/5xx y errores de red."""
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}{path}"
        headers = {"api_access_token": self.api_token}
        last_error = None
        for attempt in range(1, attempts + 1):
            self._throttle()
            try:
                resp = self.session.request(method, url, headers=headers,
                                            json=json_body, timeout=30)
            except requests.RequestException as exc:
                last_error = exc
            else:
                if resp.status_code in RETRYABLE_STATUS:
                    last_error = ChatwootAPIError(f"HTTP {resp.status_code} en {method} {path}")
                elif 200 <= resp.status_code < 300:
                    try:
                        return resp.json()
                    except ValueError:
                        return {}
                else:
                    raise ChatwootAPIError(
                        f"HTTP {resp.status_code} en {method} {path}: {resp.text[:200]}"
                    )
            if attempt < attempts:
                self._sleep(min(2 ** attempt, 8))
        raise ChatwootAPIError(f"Agotados {attempts} intentos en {method} {path}: {last_error}")

    @staticmethod
    def _extract_contacts(data):
        if isinstance(data, list):
            return data
        payload = data.get("payload") if isinstance(data, dict) else None
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get("contacts"), list):
            return payload["contacts"]
        return []

    @staticmethod
    def _contact_from_response(data):
        payload = data.get("payload") if isinstance(data, dict) else None
        if isinstance(payload, dict):
            return payload.get("contact") or payload
        return {}

    # -- contactos -----------------------------------------------------------

    def search_contact_by_phone(self, phone):
        """Busca un contacto por teléfono; devuelve el match exacto o None."""
        data = self.request("GET", f"/contacts/search?q={quote(phone)}")
        for contact in self._extract_contacts(data):
            if normalize_phone(contact.get("phone_number")) == phone:
                return contact
        return None

    def create_contact(self, contact):
        body = {
            "name": contact["name"] or "",
            "phone_number": contact["phone"] or "",
            "email": contact["email"] or "",
            "custom_attributes": contact["custom_attributes"],
        }
        if contact["identifier"]:
            body["identifier"] = contact["identifier"]
        data = self.request("POST", "/contacts", json_body=body)
        return self._contact_from_response(data)

    def update_contact(self, contact_id, name, email, custom_attributes):
        body = {"custom_attributes": custom_attributes}
        if name:
            body["name"] = name
        if email:
            body["email"] = email
        return self.request("PUT", f"/contacts/{contact_id}", json_body=body)

    def set_contact_labels(self, contact_id, labels):
        if labels:
            self.request("POST", f"/contacts/{contact_id}/labels", json_body={"labels": labels})

    # -- labels y atributos ---------------------------------------------------

    def existing_labels(self):
        data = self.request("GET", "/labels")
        payload = data.get("payload", []) if isinstance(data, dict) else []
        return extract_label_titles(payload)

    def ensure_labels(self, labels, dry_run=False):
        """Crea las labels faltantes. Devuelve la lista de las creadas."""
        existing = {slugify_label(t) for t in self.existing_labels()}
        created = []
        for label in labels:
            if label in existing:
                continue
            if not dry_run:
                self.request("POST", "/labels", json_body={"title": label})
            created.append(label)
            existing.add(label)
        return created

    def existing_attribute_keys(self):
        data = self.request("GET", "/custom_attribute_definitions")
        payload = data.get("payload", []) if isinstance(data, dict) else []
        keys = set()
        for item in payload:
            if isinstance(item, dict) and item.get("attribute_key"):
                keys.add(item["attribute_key"])
        return keys

    def ensure_custom_attributes(self, attr_types, dry_run=False):
        """Crea las custom attribute definitions faltantes (modelo: contacto).

        attr_types: {attribute_key: attribute_display_type}.
        """
        existing = self.existing_attribute_keys()
        created = []
        for key, display_type in attr_types.items():
            if key in existing:
                continue
            body = {
                "attribute_display_name": key.replace("_", " ").title(),
                "attribute_key": key,
                "attribute_display_type": display_type,
                "attribute_model": 1,
            }
            if not dry_run:
                self.request("POST", "/custom_attribute_definitions", json_body=body)
            created.append(key)
        return created


# ---------------------------------------------------------------------------
# Orquestación de la importación
# ---------------------------------------------------------------------------

def run_import(client, contacts, update_existing=False, dry_run=False):
    """Ejecuta la importación completa. Devuelve el resumen."""
    summary = {
        "total": len(contacts),
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    }

    all_labels = sorted({label for c in contacts for label in c["labels"]})
    attr_values = {}
    for contact in contacts:
        for key, value in contact["custom_attributes"].items():
            attr_values.setdefault(key, []).append(value)
    attr_types = {key: infer_attribute_type(values) for key, values in attr_values.items()}

    logger.info("Labels a asegurar: %s", all_labels or "(ninguna)")
    logger.info("Atributos a asegurar: %s", attr_types or "(ninguno)")
    client.ensure_labels(all_labels, dry_run=dry_run)
    client.ensure_custom_attributes(attr_types, dry_run=dry_run)

    for index, contact in enumerate(contacts, 1):
        label = contact["name"] or contact["phone"] or contact["email"]
        try:
            existing = None
            if contact["phone"]:
                existing = client.search_contact_by_phone(contact["phone"])

            if existing:
                if not update_existing:
                    logger.info("[%d/%d] Existente, se omite: %s", index, summary["total"], label)
                    summary["skipped"] += 1
                    continue
                if dry_run:
                    summary["updated"] += 1
                    continue
                contact_id = existing.get("id")
                merged_attrs = dict(existing.get("custom_attributes") or {})
                merged_attrs.update(contact["custom_attributes"])
                existing_label_slugs = {
                    slug for slug in (
                        slugify_label(t) for t in extract_label_titles(existing.get("labels"))
                    )
                    if slug
                }
                merged_labels = sorted(existing_label_slugs | set(contact["labels"]))
                client.update_contact(contact_id, existing.get("name") or contact["name"],
                                      existing.get("email") or contact["email"], merged_attrs)
                client.set_contact_labels(contact_id, merged_labels)
                logger.info("[%d/%d] Actualizado: %s", index, summary["total"], label)
                summary["updated"] += 1
                continue

            if dry_run:
                logger.info("[%d/%d] (dry-run) Se crearía: %s", index, summary["total"], label)
                summary["created"] += 1
                continue

            created = client.create_contact(contact)
            contact_id = (created or {}).get("id")
            if contact_id:
                client.set_contact_labels(contact_id, contact["labels"])
            else:
                logger.warning("[%d/%d] Respuesta sin id al crear: %s", index, summary["total"], label)
            logger.info("[%d/%d] Creado: %s", index, summary["total"], label)
            summary["created"] += 1

        except (ChatwootAPIError, requests.RequestException) as exc:
            logger.warning("[%d/%d] FALLO %s: %s", index, summary["total"], label, exc)
            summary["failed"] += 1
            summary["errors"].append({"contact": contact, "error": str(exc)})

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Importa contactos de ManyChat (JSON) a la API de ChatWoot."
    )
    parser.add_argument("--input", required=True, help="JSON exportado de ManyChat")
    parser.add_argument("--chatwoot-url", default=os.environ.get("CHATWOOT_URL", ""),
                        help="Ej. https://chat.tudominio.com (o env CHATWOOT_URL)")
    parser.add_argument("--account-id", type=int,
                        default=int(os.environ.get("CHATWOOT_ACCOUNT_ID", "0") or 0),
                        help="ID de cuenta ChatWoot (o env CHATWOOT_ACCOUNT_ID)")
    parser.add_argument("--api-token", default=os.environ.get("CHATWOOT_API_TOKEN", ""),
                        help="Token de agente/admin (o env CHATWOOT_API_TOKEN)")
    parser.add_argument("--rate", type=float, default=DEFAULT_RATE,
                        help=f"Requests por segundo (default {DEFAULT_RATE})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo lecturas: no crea nada, muestra lo que haría")
    parser.add_argument("--update-existing", action="store_true",
                        help="Actualizar atributos/labels de contactos ya existentes")
    parser.add_argument("--report", default="", help="Escribir resumen JSON en este archivo")
    return parser.parse_args(argv)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:  # opcional: carga .env del repo si está disponible
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    args = parse_args(argv)
    if not args.chatwoot_url or not args.account_id or not args.api_token:
        logger.error("Faltan --chatwoot-url / --account-id / --api-token "
                     "(o las env CHATWOOT_URL / CHATWOOT_ACCOUNT_ID / CHATWOOT_API_TOKEN)")
        return 2

    try:
        rows = load_contacts(args.input)
    except (OSError, ValueError) as exc:
        logger.error("No se pudo leer la entrada %s: %s", args.input, exc)
        return 2

    contacts, invalid, duplicates = prepare_contacts(rows)
    logger.info("Filas leídas: %d · contactos válidos: %d · inválidos: %d · duplicados fusionados: %d",
                len(rows), len(contacts), invalid, duplicates)
    if not contacts:
        logger.error("No hay contactos para importar")
        return 2

    client = ChatwootClient(args.chatwoot_url, args.account_id, args.api_token, rate_per_sec=args.rate)
    summary = run_import(client, contacts, update_existing=args.update_existing, dry_run=args.dry_run)
    summary.update({
        "input": args.input,
        "rows_read": len(rows),
        "invalid_rows": invalid,
        "duplicates_merged": duplicates,
        "dry_run": args.dry_run,
    })

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        logger.info("Reporte escrito en %s", args.report)

    logger.info("Resumen: %d creados · %d actualizados · %d omitidos · %d fallidos",
                summary["created"], summary["updated"], summary["skipped"], summary["failed"])
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
