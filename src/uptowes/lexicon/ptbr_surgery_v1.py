# src/uptowes/lexicon/ptbr_surgery_v1.py
# Lexicon IR (retrieval-only). Nao e verdade clinica.

LEX_GROUPS = {
    "g_antibioticoterapia": {
        "canonical": "antibioticoterapia",
        "variants": ["antibioticoterapia", "atb", "antibiotico", "antibioticos"],
        "is_rare": True,
    },
    "g_apendicite": {
        "canonical": "apendicite",
        "variants": ["apendicite"],
        "is_anchor_hint": True,
    },
    "g_alvarado": {
        "canonical": "alvarado",
        "variants": ["alvarado"],
    },
}

LEX_ALIASES = {
    "antibioticoterapia": "g_antibioticoterapia",
    "atb": "g_antibioticoterapia",
    "antibiotico": "g_antibioticoterapia",
    "antibioticos": "g_antibioticoterapia",
    "apendicite": "g_apendicite",
    "alvarado": "g_alvarado",
}

# tokens curtos (2-3 chars) so entram se estiverem aqui
SHORT_TOKEN_ALLOWLIST = {"atb", "has", "iam", "tep", "tvp", "pcr", "ercp", "cpre"}
