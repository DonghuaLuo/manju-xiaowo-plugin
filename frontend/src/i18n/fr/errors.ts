import type enErrors from "../en/errors";

export default {
    "unknown_error": "Une erreur inconnue est survenue",
    "network_error": "Erreur réseau, veuillez vérifier votre connexion",
    "unauthorized": "Non autorisé, veuillez vous reconnecter",
    "forbidden": "Permission refusée",
    "not_found": "Ressource introuvable",
    "server_error": "Erreur serveur, veuillez réessayer plus tard",
    "validation_error": "Échec de la validation",
    "source_unsupported_format": "Format source non pris en charge : {{ext}}",
    "source_decode_failed": "Impossible de décoder \"{{filename}}\" (tentatives : {{tried}})",
    "source_corrupt_file": "Le fichier source \"{{filename}}\" ne peut pas être analysé : {{reason}}",
    "source_too_large": "Le fichier source \"{{filename}}\" est trop volumineux ({{size_mb}} Mo > {{limit_mb}} Mo)",
    "source_conflict": "Le fichier source \"{{existing}}\" existe déjà",
    "image_endpoint_mismatch_no_i2i": "Le modèle {{model}} prend uniquement en charge texte vers image (pas de /v1/images/edits)",
    "image_endpoint_mismatch_no_t2i": "Le modèle {{model}} prend uniquement en charge image vers image (images de référence requises)",
    "image_capability_missing_i2i": "{{provider}}/{{model}} ne prend pas en charge image vers image ; configurez un modèle par défaut compatible avec l'édition d'images",
    "image_capability_missing_t2i": "{{provider}}/{{model}} ne prend pas en charge texte vers image ; configurez un modèle par défaut compatible texte vers image",
  } satisfies Record<keyof typeof enErrors, string>;
