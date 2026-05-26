import type enErrors from "../en/errors";

export default {
    "unknown_error": "不明なエラーが発生しました",
    "network_error": "ネットワークエラーです。接続を確認してください",
    "unauthorized": "認証されていません。再度ログインしてください",
    "forbidden": "権限がありません",
    "not_found": "リソースが見つかりません",
    "server_error": "サーバーエラーです。後でもう一度お試しください",
    "validation_error": "検証に失敗しました",
    "source_unsupported_format": "未対応のソース形式: {{ext}}",
    "source_decode_failed": "\"{{filename}}\" をデコードできませんでした（試行: {{tried}}）",
    "source_corrupt_file": "ソースファイル \"{{filename}}\" を解析できません: {{reason}}",
    "source_too_large": "ソースファイル \"{{filename}}\" が大きすぎます（{{size_mb}} MB > {{limit_mb}} MB）",
    "source_conflict": "ソースファイル \"{{existing}}\" は既に存在します",
    "image_endpoint_mismatch_no_i2i": "モデル {{model}} はテキストから画像のみ対応しています（/v1/images/edits なし）",
    "image_endpoint_mismatch_no_t2i": "モデル {{model}} は画像から画像のみ対応しています（参照画像が必要）",
    "image_capability_missing_i2i": "{{provider}}/{{model}} は画像から画像に対応していません。画像編集対応の既定モデルを設定してください",
    "image_capability_missing_t2i": "{{provider}}/{{model}} はテキストから画像に対応していません。テキストから画像対応の既定モデルを設定してください",
  } satisfies Record<keyof typeof enErrors, string>;
