"""Small auditable intent lexicon, not an embedding model or precision claim."""

import re


POLICY_VERSION = "intent-metadata.v1"
INTENTS = {
    "text-to-image": ("text-to-image",),
    "camera-motion": ("camera control", "camera trajectory"),
    "reverse-engineering": ("reverse engineering", "decompiler"),
}
ALIASES = {"ai画画": "text-to-image", "ai绘画": "text-to-image", "运镜": "camera-motion",
           "逆向": "reverse-engineering"}


def query_plan(query, intent=None, literal=False):
    if intent is not None and intent not in INTENTS:
        raise ValueError("unknown intent")
    selected = intent or (None if literal else ALIASES.get(query.strip().casefold()))
    queries = list(dict.fromkeys([query] + ([] if literal or selected is None else list(INTENTS[selected]))))
    return {"policy": POLICY_VERSION, "original_query": query, "intent": selected,
            "intent_origin": "explicit" if intent else "known_exact_alias" if selected else "none",
            "expansion": "disabled" if literal else "bounded_exact_lexicon", "queries": queries,
            "scope": "at most three explicit queries; no exhaustive semantic recall guarantee"}


def role_hint(row, intent):
    text = ((row.get("full_name") or "") + " " + (row.get("description") or "")[:512]).casefold()
    def has(pattern):
        return bool(re.search(pattern, text))
    reasons = []
    if has(r"\b(?:awesome|tutorials?|resource list|curated|survey|cheatsheet|course|guide|manual)\b|thousands of resources|教程|资源汇编|资料合集") or "course" in (row.get("full_name") or "").casefold():
        status, reasons = "REJECT_HINT", ["resource_or_tutorial_not_engine"]
    elif has(r"\b(?:skills?|mcp|ai suite|multi-model chats?|personas|api wrapper|prompt collection)\b"):
        status, reasons = "UNKNOWN", ["agent_wrapper_or_multi_tool_suite_needs_source_review"]
    elif intent == "text-to-image":
        if has(r"\b(?:image[- ]to[- ]text|image captioning|text recognition)\b"):
            status, reasons = "UNKNOWN", ["reverse_direction_or_mixed_capability_needs_source_review"]
        elif has(r"\b(?:text[- ]to[- ]image|text2image|t2i)\b|文本生成图像|ai绘画|ai画画") and has(
                r"\b(?:generat\w*|diffusion|synthesis|implement\w*|inference|model|library|pytorch)\b|生成|推理"):
            status = "MATCH_HINT"
        else:
            status, reasons = "UNKNOWN", ["generator_capability_unverified"]
    elif intent == "camera-motion":
        if has(r"\b(?:webcam|obsbot|surveillance|dslr|security camera|screen record\w*|camera recorder)\b"):
            status, reasons = "REJECT_HINT", ["hardware_recording_or_surveillance_role_signal"]
        elif has(r"\bdataset\b|human pose estimation|camera calibration"):
            status, reasons = "UNKNOWN", ["dataset_reconstruction_or_calibration_not_generation_proof"]
        elif has(r"\bcamera[\s_-]+(?:trajector\w*|poses?|motion|movement|control\w*)\b") and has(
                r"\b(?:video generat\w*|video diffusion|generative|diffusion|novel view|render\w*|world model)\b"):
            status = "MATCH_HINT"
        else:
            status, reasons = "UNKNOWN", ["generative_camera_conditioning_unverified"]
    elif intent == "reverse-engineering":
        if has(r"\b(?:credential theft|password stealer|keylogger)\b"):
            status, reasons = "REJECT_HINT", ["outside_authorized_static_analysis_role"]
        elif has(r"\b(?:decompil\w*|disassembl\w*|reverse engineering|static (?:binary|program) analysis)\b"):
            status = "MATCH_HINT"
        else:
            status, reasons = "UNKNOWN", ["static_analysis_capability_unverified"]
    else:
        status, reasons = "UNKNOWN", ["no_supported_intent"]
    return {"policy": POLICY_VERSION, "intent": intent, "status": status, "reasons": reasons,
            "evidence": "bounded repository name/description only; not source or safety approval"}
