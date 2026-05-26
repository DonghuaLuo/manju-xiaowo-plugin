import baseTemplates from "../en/templates";
import { mergeNamespace, type DeepPartialStrings, type StringResources } from "../_helpers";
import type enTemplates from "../en/templates";

type TemplateResource = StringResources<typeof enTemplates>;

const templateOverrides = {
    category: { custom: "사용자 지정", live: "실사", anim: "애니메이션" },
    name: {
      live_cinematic_ancient: "영화풍 사극",
      live_ancient_xianxia: "고전 선협",
      live_premium_drama: "프리미엄 드라마",
      live_cinema: "극장 영화",
      live_spartan: "스파르타 서사",
      live_cyberpunk: "실사 사이버펑크",
      anim_3d_cg: "3D 게임 CG",
      anim_cn_3d: "중국 3D",
      anim_us_3d: "미국 3D 애니메이션",
      anim_ink_wushan: "강렬한 수묵",
      anim_ink_papercut: "수묵과 종이 오리기",
      anim_felt: "펠트 스톱모션",
      anim_clay: "클레이 스톱모션",
      anim_jp_horror: "일본 호러",
      anim_kr_webtoon: "한국 웹툰",
      anim_cyberpunk: "애니 사이버펑크",
      anim_90s_retro: "90년대 레트로 애니",
    },
    default_hint: "기본 모델은 대시보드 > 설정 > 모델 선택에서 변경할 수 있습니다",
    current_global_default: "현재 전역 기본값: {{value}}",
    use_global_default: "전역 기본값 사용",
    model_video: "비디오 모델",
    model_image: "이미지 모델",
    model_image_t2i: "이미지 모델(T2I)",
    model_image_i2i: "이미지 모델(I2I)",
    model_image_dual_hint: "T2I/I2I 각각에 맞는 기능을 가진 모델 선택을 권장합니다",
    model_text_script: "각본 생성 모델",
    model_text_overview: "개요 생성 모델",
    model_text_style: "스타일 분석 모델",
    duration_label: "기본 길이",
    duration_auto: "자동",
    resolution_label: "해상도",
    resolution_default_placeholder: "기본값(미설정)",
    tab_custom_desc: "스타일 참조 이미지를 업로드하면 AI가 분석합니다. 이 탭을 선택하면 템플릿 선택이 해제됩니다.",
    upload_reference: "스타일 참조 업로드",
    supported_formats: "PNG / JPG / WEBP",
    template_selected_default: "(기본값)",
    wizard_step_basics: "기본",
    wizard_step_models: "모델",
    wizard_step_style: "스타일",
    next_step: "다음",
    prev_step: "뒤로",
  } satisfies DeepPartialStrings<TemplateResource>;

export default mergeNamespace(baseTemplates, templateOverrides);
