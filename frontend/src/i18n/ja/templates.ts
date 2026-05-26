import baseTemplates from "../en/templates";
import { mergeNamespace, type DeepPartialStrings, type StringResources } from "../_helpers";
import type enTemplates from "../en/templates";

type TemplateResource = StringResources<typeof enTemplates>;

const templateOverrides = {
    category: { custom: "カスタム", live: "実写", anim: "アニメーション" },
    name: {
      live_cinematic_ancient: "映画的な歴史劇",
      live_ancient_xianxia: "古装仙侠",
      live_premium_drama: "プレミアムドラマ",
      live_cinema: "劇場映画",
      live_spartan: "スパルタ叙事詩",
      live_cyberpunk: "実写サイバーパンク",
      anim_3d_cg: "3DゲームCG",
      anim_cn_3d: "中国3D",
      anim_us_3d: "米国3Dアニメ",
      anim_ink_wushan: "硬派な墨絵",
      anim_ink_papercut: "墨絵と切り紙",
      anim_felt: "フェルトのストップモーション",
      anim_clay: "クレイストップモーション",
      anim_jp_horror: "日本ホラー",
      anim_kr_webtoon: "韓国ウェブトゥーン",
      anim_cyberpunk: "アニメサイバーパンク",
      anim_90s_retro: "90年代レトロアニメ",
    },
    default_hint: "既定モデルはダッシュボード > 設定 > モデル選択で変更できます",
    current_global_default: "現在のグローバル既定値: {{value}}",
    use_global_default: "グローバル既定値を使用",
    model_video: "動画モデル",
    model_image: "画像モデル",
    model_image_t2i: "画像モデル (T2I)",
    model_image_i2i: "画像モデル (I2I)",
    model_image_dual_hint: "T2I/I2I それぞれに対応する能力のモデルを選ぶことを推奨します",
    model_text_script: "脚本生成モデル",
    model_text_overview: "概要生成モデル",
    model_text_style: "スタイル分析モデル",
    duration_label: "既定の長さ",
    duration_auto: "自動",
    resolution_label: "解像度",
    resolution_default_placeholder: "既定（未設定）",
    tab_custom_desc: "スタイル参照画像をアップロードすると AI が分析します。このタブを選ぶとテンプレート選択は解除されます。",
    upload_reference: "スタイル参照をアップロード",
    supported_formats: "PNG / JPG / WEBP",
    template_selected_default: "（既定）",
    wizard_step_basics: "基本",
    wizard_step_models: "モデル",
    wizard_step_style: "スタイル",
    next_step: "次へ",
    prev_step: "戻る",
  } satisfies DeepPartialStrings<TemplateResource>;

export default mergeNamespace(baseTemplates, templateOverrides);
