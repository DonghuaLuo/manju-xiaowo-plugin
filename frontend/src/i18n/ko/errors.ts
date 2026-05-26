import type enErrors from "../en/errors";

export default {
    "unknown_error": "알 수 없는 오류가 발생했습니다",
    "network_error": "네트워크 오류입니다. 연결을 확인해 주세요",
    "unauthorized": "인증되지 않았습니다. 다시 로그인해 주세요",
    "forbidden": "권한이 없습니다",
    "not_found": "리소스를 찾을 수 없습니다",
    "server_error": "서버 오류입니다. 나중에 다시 시도해 주세요",
    "validation_error": "검증에 실패했습니다",
    "source_unsupported_format": "지원하지 않는 원본 형식: {{ext}}",
    "source_decode_failed": "\"{{filename}}\"을(를) 디코딩하지 못했습니다(시도: {{tried}})",
    "source_corrupt_file": "원본 파일 \"{{filename}}\"을(를) 분석할 수 없습니다: {{reason}}",
    "source_too_large": "원본 파일 \"{{filename}}\"이(가) 너무 큽니다({{size_mb}} MB > {{limit_mb}} MB)",
    "source_conflict": "원본 파일 \"{{existing}}\"이(가) 이미 있습니다",
    "image_endpoint_mismatch_no_i2i": "모델 {{model}}은 텍스트-이미지만 지원합니다(/v1/images/edits 없음)",
    "image_endpoint_mismatch_no_t2i": "모델 {{model}}은 이미지-이미지만 지원합니다(참조 이미지 필요)",
    "image_capability_missing_i2i": "{{provider}}/{{model}}은(는) 이미지-이미지를 지원하지 않습니다. 이미지 편집을 지원하는 기본 모델을 설정하세요",
    "image_capability_missing_t2i": "{{provider}}/{{model}}은(는) 텍스트-이미지를 지원하지 않습니다. 텍스트-이미지를 지원하는 기본 모델을 설정하세요",
  } satisfies Record<keyof typeof enErrors, string>;
