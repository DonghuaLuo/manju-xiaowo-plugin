import type enErrors from "../en/errors";

export default {
    "unknown_error": "Ein unbekannter Fehler ist aufgetreten",
    "network_error": "Netzwerkfehler, bitte Verbindung prüfen",
    "unauthorized": "Nicht autorisiert, bitte erneut anmelden",
    "forbidden": "Zugriff verweigert",
    "not_found": "Ressource nicht gefunden",
    "server_error": "Serverfehler, bitte später erneut versuchen",
    "validation_error": "Validierung fehlgeschlagen",
    "source_unsupported_format": "Nicht unterstütztes Quellformat: {{ext}}",
    "source_decode_failed": "\"{{filename}}\" konnte nicht dekodiert werden (versucht: {{tried}})",
    "source_corrupt_file": "Quelldatei \"{{filename}}\" kann nicht analysiert werden: {{reason}}",
    "source_too_large": "Quelldatei \"{{filename}}\" ist zu groß ({{size_mb}} MB > {{limit_mb}} MB)",
    "source_conflict": "Quelldatei \"{{existing}}\" existiert bereits",
    "image_endpoint_mismatch_no_i2i": "Modell {{model}} unterstützt nur Text-zu-Bild (kein /v1/images/edits)",
    "image_endpoint_mismatch_no_t2i": "Modell {{model}} unterstützt nur Bild-zu-Bild (Referenzbilder erforderlich)",
    "image_capability_missing_i2i": "{{provider}}/{{model}} unterstützt kein Bild-zu-Bild; konfigurieren Sie ein Standardmodell mit Bildbearbeitung",
    "image_capability_missing_t2i": "{{provider}}/{{model}} unterstützt kein Text-zu-Bild; konfigurieren Sie ein Standardmodell mit Text-zu-Bild",
  } satisfies Record<keyof typeof enErrors, string>;
