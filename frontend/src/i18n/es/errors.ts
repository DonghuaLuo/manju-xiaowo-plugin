import type enErrors from "../en/errors";

export default {
    "unknown_error": "Se produjo un error desconocido",
    "network_error": "Error de red, comprueba la conexión",
    "unauthorized": "No autorizado, inicia sesión de nuevo",
    "forbidden": "Permiso denegado",
    "not_found": "Recurso no encontrado",
    "server_error": "Error del servidor, inténtalo más tarde",
    "validation_error": "Validación fallida",
    "source_unsupported_format": "Formato de fuente no compatible: {{ext}}",
    "source_decode_failed": "No se pudo decodificar \"{{filename}}\" (intentos: {{tried}})",
    "source_corrupt_file": "No se puede analizar el archivo fuente \"{{filename}}\": {{reason}}",
    "source_too_large": "El archivo fuente \"{{filename}}\" es demasiado grande ({{size_mb}} MB > {{limit_mb}} MB)",
    "source_conflict": "El archivo fuente \"{{existing}}\" ya existe",
    "image_endpoint_mismatch_no_i2i": "El modelo {{model}} solo admite texto a imagen (sin /v1/images/edits)",
    "image_endpoint_mismatch_no_t2i": "El modelo {{model}} solo admite imagen a imagen (requiere imágenes de referencia)",
    "image_capability_missing_i2i": "{{provider}}/{{model}} no admite imagen a imagen; configura un modelo predeterminado que admita edición de imágenes",
    "image_capability_missing_t2i": "{{provider}}/{{model}} no admite texto a imagen; configura un modelo predeterminado que admita texto a imagen",
  } satisfies Record<keyof typeof enErrors, string>;
