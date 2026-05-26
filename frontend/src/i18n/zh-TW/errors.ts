import type enErrors from "../en/errors";

export default {
    "unknown_error": "發生未知錯誤",
    "network_error": "網路錯誤，請檢查連線",
    "unauthorized": "未授權，請重新登入",
    "forbidden": "權限不足",
    "not_found": "找不到資源",
    "server_error": "伺服器錯誤，請稍後再試",
    "validation_error": "驗證失敗",
    "source_unsupported_format": "不支援的源格式：{{ext}}",
    "source_decode_failed": "無法解碼「{{filename}}」（已嘗試：{{tried}}）",
    "source_corrupt_file": "源檔案「{{filename}}」無法解析：{{reason}}",
    "source_too_large": "源檔案「{{filename}}」過大（{{size_mb}} MB > {{limit_mb}} MB）",
    "source_conflict": "源檔案「{{existing}}」已存在",
    "image_endpoint_mismatch_no_i2i": "模型 {{model}} 僅支援文字生圖（沒有 /v1/images/edits）",
    "image_endpoint_mismatch_no_t2i": "模型 {{model}} 僅支援圖生圖（需要參考圖片）",
    "image_capability_missing_i2i": "{{provider}}/{{model}} 不支援圖生圖；請設定支援圖片編輯的預設模型",
    "image_capability_missing_t2i": "{{provider}}/{{model}} 不支援文字生圖；請設定支援文字生圖的預設模型",
  } satisfies Record<keyof typeof enErrors, string>;
