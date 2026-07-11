from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


VEHICLE_META_FILES = ("vehicles.meta", "carvariations.meta", "carcols.meta")


def clean_model_name(name: str) -> str:
    lower = name.lower()
    if lower.endswith("_hi") or lower.endswith("+hi"):
        return name[:-3]
    return name


def vehicle_resource_root(stream_dir: Path) -> Path | None:
    stream_dir = stream_dir.resolve()
    candidates = [stream_dir]
    if stream_dir.name.lower() == "stream":
        candidates.insert(0, stream_dir.parent)
    for candidate in candidates:
        if any((candidate / name).is_file() for name in VEHICLE_META_FILES):
            return candidate
    return None


def read_xml(path: Path) -> ET.Element | None:
    if not path.is_file():
        return None
    try:
        return ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise RuntimeError(f"Invalid XML: {path}: {exc}") from exc


def text_of(node: ET.Element | None, name: str) -> str:
    if node is None:
        return ""
    return (node.findtext(name) or "").strip()


def item_values(node: ET.Element | None, name: str) -> list[str]:
    if node is None:
        return []
    return [
        (item.text or "").strip()
        for item in node.findall(f"./{name}/Item")
        if (item.text or "").strip()
    ]


def bool_value(node: ET.Element | None, name: str) -> bool:
    if node is None:
        return False
    value_node = node.find(name)
    if value_node is None:
        return False
    value = (value_node.get("value") or value_node.text or "").strip().lower()
    return value in {"1", "true", "yes"}


def normalize_extra_name(value: str) -> str:
    value = value.strip().lower().replace("-", "_")
    if not value:
        return ""
    if value.isdigit():
        return f"extra_{int(value)}"
    if value.startswith("extra"):
        suffix = value[5:].lstrip("_ ")
        if suffix.isdigit():
            return f"extra_{int(suffix)}"
    return value


def stream_yft_map(stream_dir: Path) -> dict[str, str]:
    by_model: dict[str, str] = {}
    for path in sorted(stream_dir.glob("*.yft")):
        model = clean_model_name(path.stem).lower()
        existing = by_model.get(model)
        if existing is None:
            by_model[model] = path.name
            continue
        existing_hi = Path(existing).stem.lower().endswith(("_hi", "+hi"))
        current_hi = path.stem.lower().endswith(("_hi", "+hi"))
        if existing_hi and not current_hi:
            by_model[model] = path.name
    return by_model


def parse_vehicle_models(resource_root: Path, stream_dir: Path) -> list[str]:
    available = stream_yft_map(stream_dir)
    models: list[str] = []
    for meta_name, query in (
        ("carvariations.meta", ".//variationData/Item/modelName"),
        ("vehicles.meta", ".//InitDatas/Item/modelName"),
    ):
        root = read_xml(resource_root / meta_name)
        if root is None:
            continue
        for node in root.findall(query):
            value = (node.text or "").strip()
            if value:
                models.append(value)

    out: list[str] = []
    seen: set[str] = set()
    for model in models:
        key = model.lower()
        if key in available and key not in seen:
            seen.add(key)
            out.append(model)
    return out


def parse_kits(resource_root: Path) -> dict[str, dict[str, object]]:
    root = read_xml(resource_root / "carcols.meta")
    if root is None:
        return {}

    kits: dict[str, dict[str, object]] = {}
    for kit_node in root.findall(".//Kits/Item"):
        kit_name = text_of(kit_node, "kitName")
        if not kit_name:
            continue
        visible_mods: list[dict[str, object]] = []
        for item in kit_node.findall("./visibleMods/Item"):
            model = text_of(item, "modelName")
            if not model:
                continue
            visible_mods.append(
                {
                    "model": model,
                    "type": text_of(item, "type"),
                    "bone": text_of(item, "bone") or "chassis",
                    "linked": [
                        (link.text or "").strip()
                        for link in item.findall("./linkedModels/Item")
                        if (link.text or "").strip()
                    ],
                    "turn_off_bones": item_values(item, "turnOffBones"),
                    "turn_off_extra": bool_value(item, "turnOffExtra"),
                }
            )

        link_bones: dict[str, str] = {}
        for item in kit_node.findall("./linkMods/Item"):
            model = text_of(item, "modelName")
            bone = text_of(item, "bone")
            if model and bone:
                link_bones[model.lower()] = bone
        kits[kit_name.lower()] = {
            "name": kit_name,
            "visible_mods": visible_mods,
            "link_bones": link_bones,
        }
    return kits


def kit_names_for_model(resource_root: Path, model: str) -> list[str]:
    root = read_xml(resource_root / "carvariations.meta")
    if root is None:
        return []
    for item in root.findall(".//variationData/Item"):
        if text_of(item, "modelName").lower() != model.lower():
            continue
        return [
            (kit.text or "").strip()
            for kit in item.findall("./kits/Item")
            if (kit.text or "").strip()
        ]
    return []


def extras_for_model(resource_root: Path, model: str) -> dict[str, list[str]]:
    root = read_xml(resource_root / "vehicles.meta")
    if root is None:
        return {"included": [], "required": []}
    for item in root.findall(".//InitDatas/Item"):
        if text_of(item, "modelName").lower() != model.lower():
            continue
        return {
            "included": [normalize_extra_name(value) for value in item_values(item, "extraIncludes")],
            "required": [normalize_extra_name(value) for value in item_values(item, "requiredExtras")],
        }
    return {"included": [], "required": []}


def resolve_kit(resource_root: Path, model: str, requested_kit: str):
    kits = parse_kits(resource_root)
    if not kits:
        return "", [], {}
    if requested_kit:
        kit = kits.get(requested_kit.lower())
        if kit is None:
            raise RuntimeError(f"Vehicle assembly kit not found: {requested_kit}")
        return kit["name"], kit["visible_mods"], kit["link_bones"]
    for kit_name in kit_names_for_model(resource_root, model):
        kit = kits.get(kit_name.lower())
        if kit is not None:
            return kit["name"], kit["visible_mods"], kit["link_bones"]
    first = next(iter(kits.values()))
    return first["name"], first["visible_mods"], first["link_bones"]


def mod_exists(mod: dict[str, object], available: dict[str, str]) -> bool:
    names = [str(mod["model"]), *[str(item) for item in mod.get("linked", [])]]
    return any(name.lower() in available for name in names)


def select_showcase_mods(visible_mods, available):
    chosen = []
    used_types: set[str] = set()
    for mod in visible_mods:
        mod_type = str(mod.get("type", "")).lower()
        if mod_type in used_types or not mod_exists(mod, available):
            continue
        used_types.add(mod_type)
        chosen.append(mod)
    return chosen


def select_explicit_mods(visible_mods, available, specs: list[str]):
    by_model = {str(mod["model"]).lower(): mod for mod in visible_mods}
    by_type: dict[str, list[dict[str, object]]] = {}
    for mod in visible_mods:
        by_type.setdefault(str(mod.get("type", "")).lower(), []).append(mod)

    chosen = []
    for spec in specs:
        raw = spec.strip()
        if not raw:
            continue
        key = raw.lower()
        index = 1
        if ":" in raw:
            left, right = raw.rsplit(":", 1)
            key = left.strip().lower()
            try:
                index = max(1, int(right.strip()))
            except ValueError:
                raise RuntimeError(f"Invalid vehicle mod selector: {raw}") from None
        mod = by_model.get(key)
        if mod is None:
            matches = [item for item in by_type.get(key, []) if mod_exists(item, available)]
            if matches:
                if index > len(matches):
                    raise RuntimeError(f"Vehicle mod selector out of range: {raw}")
                mod = matches[index - 1]
        if mod is None and key in available:
            mod = {
                "model": raw,
                "type": "EXPLICIT",
                "bone": "chassis",
                "linked": [],
                "turn_off_bones": [],
                "turn_off_extra": False,
            }
        if mod is not None and mod_exists(mod, available):
            chosen.append(mod)
    return chosen


def build_assembly_plan(
    resource_root: Path,
    stream_dir: Path,
    base_model: str,
    mode: str = "auto",
    requested_kit: str = "",
    mod_specs: list[str] | None = None,
) -> dict[str, object]:
    available = stream_yft_map(stream_dir)
    base_key = base_model.lower()
    if base_key not in available:
        raise RuntimeError(f"Vehicle assembly base YFT not found: {base_model}")

    specs = list(mod_specs or [])
    effective_mode = "showcase" if mode == "auto" and ((resource_root / "carcols.meta").is_file() or specs) else mode
    if effective_mode == "auto":
        effective_mode = "none"
    if effective_mode == "none":
        kit_name, visible_mods, link_bones = "", [], {}
        selected_mods = []
    else:
        kit_name, visible_mods, link_bones = resolve_kit(resource_root, base_model, requested_kit)
        if specs:
            selected_mods = select_explicit_mods(visible_mods, available, specs)
        elif effective_mode == "all":
            selected_mods = [mod for mod in visible_mods if mod_exists(mod, available)]
        elif effective_mode == "showcase":
            selected_mods = select_showcase_mods(visible_mods, available)
        else:
            raise RuntimeError(f"Unknown vehicle assembly mode: {mode}")

    parts: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(model: str, bone: str, mod_type: str) -> None:
        key = model.lower()
        filename = available.get(key)
        if not filename or key in seen:
            return
        seen.add(key)
        parts.append(
            {
                "model": clean_model_name(Path(filename).stem),
                "file": filename,
                "bone": bone or link_bones.get(key, "chassis"),
                "type": mod_type,
            }
        )

    add(base_model, "chassis", "BASE")
    for mod in selected_mods:
        mod_type = str(mod.get("type", ""))
        bone = str(mod.get("bone", "")) or "chassis"
        add(str(mod["model"]), bone, mod_type)
        for linked in mod.get("linked", []):
            linked_name = str(linked)
            add(linked_name, link_bones.get(linked_name.lower(), bone), mod_type)

    disabled_bones: list[str] = []
    seen_disabled: set[str] = set()
    for mod in selected_mods:
        for bone in mod.get("turn_off_bones", []):
            name = str(bone).strip()
            key = name.lower()
            if name and key not in seen_disabled:
                seen_disabled.add(key)
                disabled_bones.append(name)

    extras = extras_for_model(resource_root, base_model)

    return {
        "enabled": len(parts) > 1,
        "mode": effective_mode,
        "kit": str(kit_name),
        "base_model": base_model,
        "parts": parts,
        "disabled_bones": disabled_bones,
        "turn_off_extra": any(bool(mod.get("turn_off_extra")) for mod in selected_mods),
        "included_extras": extras["included"],
        "required_extras": extras["required"],
    }
