"""Funcoes de taxonomia (normalizacao e qualidade)."""

from __future__ import annotations

import re
import unicodedata

from taxonomy_data import (
    _ALL_STANDARD_AREAS,
    AREA_ALIASES,
    CANONICAL_MODULE_TO_DEFAULT_AREA,  # noqa: F401  (re-export publico)
    CANONICAL_MODULES,
    MODULE_ALIASES,
    MODULE_CATEGORIES,
    MODULE_TAG_CATEGORIES,
    MODULE_TAG_PATTERN,
    NON_MODULE_TAGS,
    STANDARD_AREAS_BY_MODULE,
    TITLE_PATTERN_BASIC,
    TITLE_PATTERN_FULL,
    TITLE_PATTERN_WITH_AREA,
)


def _fold(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text.strip())
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_accents).casefold()


def normalize_module(raw: str) -> str:
    """Normaliza variacao para modulo canonico quando possivel."""
    canon = normalize_module_to_canonical(raw)
    if canon:
        return canon
    text = (raw or "").strip()
    if not text:
        return ""
    return text


def normalize_module_to_canonical(raw: str) -> str:
    """Retorna um dos 12 modulos canonicos ou string vazia se nao mapeavel."""
    text = (raw or "").strip()
    if not text:
        return ""
    if text in CANONICAL_MODULES:
        return text
    if text in MODULE_ALIASES:
        candidate = MODULE_ALIASES[text]
        if candidate in CANONICAL_MODULES:
            return candidate
    folded = _fold(text)
    for alias, canonical in MODULE_ALIASES.items():
        if _fold(alias) == folded and canonical in CANONICAL_MODULES:
            return canonical
    for module in CANONICAL_MODULES:
        if _fold(module) == folded:
            return module
    return ""


def module_category(module: str) -> str:
    text = (module or "").strip()
    if not text:
        return ""
    canon = normalize_module_to_canonical(text)
    if canon in MODULE_CATEGORIES:
        return MODULE_CATEGORIES[canon]
    return "Não mapeado"


def is_canonical_module(module: str) -> bool:
    if not module:
        return False
    return normalize_module_to_canonical(module) in CANONICAL_MODULES


def normalize_area(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if text in _ALL_STANDARD_AREAS:
        return text
    key = _fold(text)
    if key in AREA_ALIASES:
        return AREA_ALIASES[key]
    for area in _ALL_STANDARD_AREAS:
        if _fold(area) == key:
            return area
    return text


def is_standard_area(area: str, module: str = "") -> bool:
    if not area:
        return False
    canonical_area = normalize_area(area)
    if canonical_area in _ALL_STANDARD_AREAS:
        return True
    canonical_module = normalize_module(module)
    if not canonical_module:
        return False
    module_areas = STANDARD_AREAS_BY_MODULE.get(canonical_module, ())
    return canonical_area in module_areas or _fold(canonical_area) in {
        _fold(a) for a in module_areas
    }


def extract_module_tag(title: str) -> str:
    match = MODULE_TAG_PATTERN.match((title or "").strip())
    if not match:
        return ""
    return match.group(1).strip()


CUSTOM_BUCKET = "Custom/Não mapeado"
NON_MODULE_BUCKET = "Meta/Não funcional"


def _compound_module_candidates(tag: str) -> list[str]:
    """Gera candidatos para tags compostas com ' - ' (ex.: Gestão de atas - PNCP)."""
    text = (tag or "").strip()
    if not text:
        return []
    return [text]


def _resolve_compound_dash_tag(text: str) -> str | None:
    """Resolve tags com ' - ' priorizando contexto manual validado."""
    if " - " not in text:
        return None
    parts = [part.strip() for part in text.split(" - ") if part.strip()]
    if len(parts) < 2:
        return None
    left, right = parts[0], parts[-1]
    left_canon = normalize_module_to_canonical(left)
    right_canon = normalize_module_to_canonical(right)
    right_fold = _fold(right)

    if right_canon == "PNCP" and left_canon:
        return right_canon
    if right_fold in {_fold("bug"), _fold("bugs"), _fold("test"), _fold("teste")}:
        return left_canon or NON_MODULE_BUCKET
    if left_canon:
        return left_canon
    return right_canon


def _split_compound_tag(tag: str) -> str:
    """Compat: retorna o primeiro candidato de tag composta."""
    resolved = _resolve_compound_dash_tag(tag)
    if resolved:
        return resolved
    return (tag or "").strip()


def canonical_or_bucket(raw: str) -> str:
    """Um dos 12 canonicos, bucket meta/custom, ou vazio."""
    text = (raw or "").strip()
    if not text:
        return ""
    compound = _resolve_compound_dash_tag(text)
    if compound:
        if compound == NON_MODULE_BUCKET:
            return NON_MODULE_BUCKET
        if compound in CANONICAL_MODULES:
            return compound
    if text in NON_MODULE_TAGS or _fold(text) in {_fold(t) for t in NON_MODULE_TAGS}:
        return NON_MODULE_BUCKET
    canon = normalize_module_to_canonical(text)
    if canon:
        return canon
    return CUSTOM_BUCKET


def suggest_title_module_fix(title: str) -> str | None:
    text = (title or "").strip()
    match = MODULE_TAG_PATTERN.match(text)
    if not match:
        return None
    tag = match.group(1).strip()
    canon = normalize_module_to_canonical(tag)
    if not canon or _fold(tag) == _fold(canon):
        return None
    return MODULE_TAG_PATTERN.sub(f"[{canon}]", text, count=1)


def validate_title_pattern(title: str, *, strict: bool = False) -> bool:
    text = (title or "").strip()
    if strict == "full":
        return bool(TITLE_PATTERN_FULL.match(text))
    if strict:
        return bool(TITLE_PATTERN_WITH_AREA.search(text))
    return bool(TITLE_PATTERN_BASIC.match(text))


def confidence_area_label(title: str, area: str, *, git_confidence: float = 0.0) -> str:
    if git_confidence > 0:
        return f"{int(round(git_confidence * 100))}%"
    if not area:
        return ""
    if TITLE_PATTERN_WITH_AREA.search((title or "").strip()):
        return "100%"
    return "75%"


def all_module_de_para_rows() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(source: str, target: str) -> None:
        if not source or not target or target not in CANONICAL_MODULES:
            return
        key = _fold(source)
        if key in seen:
            return
        rows.append((source, target))
        seen.add(key)

    for module in CANONICAL_MODULES:
        add(module, module)
    for alias, canonical in MODULE_ALIASES.items():
        add(alias, canonical)
    for tag in MODULE_TAG_CATEGORIES:
        canon = normalize_module_to_canonical(tag)
        if canon:
            add(tag, canon)
    return rows


def all_accepted_modules_sorted() -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for module in CANONICAL_MODULES:
        if module not in seen:
            ordered.append(module)
            seen.add(module)
    for tag in sorted(MODULE_TAG_CATEGORIES, key=_fold):
        if tag not in seen:
            ordered.append(tag)
            seen.add(tag)
    return ordered


def all_module_category_rows() -> list[tuple[str, str]]:
    return [(module, MODULE_CATEGORIES[module]) for module in CANONICAL_MODULES]


def all_standard_areas_sorted() -> list[str]:
    return sorted(_ALL_STANDARD_AREAS, key=lambda x: _fold(x))


def assess_row_quality(
    title: str,
    module: str,
    area: str,
    area_confidence: float = 0.0,
) -> dict[str, str]:
    canon = normalize_module_to_canonical(module)
    if not canon and title:
        canon = normalize_module_to_canonical(extract_module_tag(title))
    mod_ok = "Sim" if canon in CANONICAL_MODULES else "Não"
    padrao = "Sim" if validate_title_pattern(title) else "Não"
    padrao_completo = "Sim" if validate_title_pattern(title, strict=True) else "Não"
    mod_ref = canon or module
    if not mod_ref:
        area_ok = "N/A"
    elif not area:
        area_ok = "Não"
    elif is_standard_area(area, mod_ref):
        area_ok = "Sim"
    else:
        area_ok = "Não"
    conf_text = confidence_area_label(title, area, git_confidence=area_confidence)
    return {
        "categoria": module_category(canon or module) if (canon or module) else "",
        "modulo_ok": mod_ok,
        "area_ok": area_ok,
        "padrao_titulo": padrao,
        "padrao_completo": padrao_completo,
        "confianca_area": conf_text,
    }
