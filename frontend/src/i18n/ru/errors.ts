import type enErrors from "../en/errors";

export default {
    "unknown_error": "Произошла неизвестная ошибка",
    "network_error": "Ошибка сети, проверьте подключение",
    "unauthorized": "Нет авторизации, войдите снова",
    "forbidden": "Доступ запрещён",
    "not_found": "Ресурс не найден",
    "server_error": "Ошибка сервера, попробуйте позже",
    "validation_error": "Ошибка проверки",
    "source_unsupported_format": "Неподдерживаемый формат источника: {{ext}}",
    "source_decode_failed": "Не удалось декодировать \"{{filename}}\" (попытки: {{tried}})",
    "source_corrupt_file": "Не удалось разобрать исходный файл \"{{filename}}\": {{reason}}",
    "source_too_large": "Исходный файл \"{{filename}}\" слишком большой ({{size_mb}} МБ > {{limit_mb}} МБ)",
    "source_conflict": "Исходный файл \"{{existing}}\" уже существует",
    "image_endpoint_mismatch_no_i2i": "Модель {{model}} поддерживает только текст-в-изображение (нет /v1/images/edits)",
    "image_endpoint_mismatch_no_t2i": "Модель {{model}} поддерживает только изображение-в-изображение (нужны референсы)",
    "image_capability_missing_i2i": "{{provider}}/{{model}} не поддерживает изображение-в-изображение; настройте модель по умолчанию с редактированием изображений",
    "image_capability_missing_t2i": "{{provider}}/{{model}} не поддерживает текст-в-изображение; настройте модель по умолчанию с текстом-в-изображение",
  } satisfies Record<keyof typeof enErrors, string>;
