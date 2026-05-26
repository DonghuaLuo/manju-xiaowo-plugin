import baseTemplates from "../en/templates";
import { mergeNamespace, type DeepPartialStrings, type StringResources } from "../_helpers";
import type enTemplates from "../en/templates";

type TemplateResource = StringResources<typeof enTemplates>;

const templateOverrides = {
    category: { custom: "Personnalisé", live: "Prise de vues réelles", anim: "Animation" },
    name: {
      live_cinematic_ancient: "Historique cinématographique",
      live_ancient_xianxia: "Xianxia historique",
      live_premium_drama: "Drama premium",
      live_cinema: "Film de cinéma",
      live_spartan: "Épopée spartiate",
      live_cyberpunk: "Cyberpunk live",
      anim_3d_cg: "CG jeu 3D",
      anim_cn_3d: "3D chinoise",
      anim_us_3d: "Animation 3D US",
      anim_ink_wushan: "Encre puissante",
      anim_ink_papercut: "Encre et papier découpé",
      anim_felt: "Stop motion feutré",
      anim_clay: "Stop motion argile",
      anim_jp_horror: "Horreur japonaise",
      anim_kr_webtoon: "Webtoon coréen",
      anim_cyberpunk: "Cyberpunk animé",
      anim_90s_retro: "Anime rétro années 90",
    },
    default_hint: "Les modèles par défaut peuvent être modifiés dans Tableau de bord > Paramètres > Sélection des modèles",
    current_global_default: "Valeur globale actuelle : {{value}}",
    use_global_default: "Utiliser la valeur globale",
    model_video: "Modèle vidéo",
    model_image: "Modèle image",
    model_image_t2i: "Modèle image (T2I)",
    model_image_i2i: "Modèle image (I2I)",
    model_image_dual_hint: "Choisissez de préférence un modèle compatible avec la capacité T2I/I2I correspondante",
    model_text_script: "Modèle de génération de script",
    model_text_overview: "Modèle de génération d'aperçu",
    model_text_style: "Modèle d'analyse de style",
    duration_label: "Durée par défaut",
    duration_auto: "auto",
    resolution_label: "Résolution",
    resolution_default_placeholder: "Par défaut (non défini)",
    tab_custom_desc: "Téléversez une image de référence de style ; l'IA l'analysera. Choisir cet onglet efface la sélection du modèle.",
    upload_reference: "Téléverser une référence de style",
    supported_formats: "PNG / JPG / WEBP",
    template_selected_default: "(par défaut)",
    wizard_step_basics: "Bases",
    wizard_step_models: "Modèles",
    wizard_step_style: "Style",
    next_step: "Suivant",
    prev_step: "Retour",
  } satisfies DeepPartialStrings<TemplateResource>;

export default mergeNamespace(baseTemplates, templateOverrides);
