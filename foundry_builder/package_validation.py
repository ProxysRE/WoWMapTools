"""Проверка связей и замкнутости переносимого каталога персонажей."""
from __future__ import annotations
import re
from typing import Any
from class_builder import ClassBuilderError, DOCUMENT_ID

STANDARD_CLASSES = frozenset({"barbarian", "bard", "cleric", "druid", "fighter", "monk", "paladin", "ranger", "rogue", "sorcerer", "warlock", "wizard"})


def walk_strings(value: Any):
    if isinstance(value, dict):
        for item in value.values():
            yield from walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_strings(item)
    elif isinstance(value, str):
        yield value


def document_groups(documents: dict) -> dict[str, list[dict]]:
    def array(key):
        result = documents.get(key, [])
        if not isinstance(result, list) or any(not isinstance(x, dict) for x in result):
            raise ClassBuilderError(f"documents.{key} должен быть массивом объектов.")
        return result
    classes = array("classes") if "classes" in documents else ([documents["class"]] if documents.get("class") is not None else [])
    if "classes" in documents and documents.get("class") is not None:
        if len(classes) != 1 or classes[0] != documents["class"]:
            raise ClassBuilderError("Конфликт singular/plural документов класса.")
    subclasses = array("subclasses") if "subclasses" in documents else ([documents["subclass"]] if documents.get("subclass") is not None else [])
    if "subclasses" in documents and documents.get("subclass") is not None:
        if len(subclasses) != 1 or subclasses[0] != documents["subclass"]:
            raise ClassBuilderError("Конфликт singular/plural документов подкласса.")
    result = {"classes": classes + subclasses, "races": array("races"), "features": array("features")}
    if documents.get("spells"):
        result["spells"] = array("spells")
    for key in ("backgrounds", "feats", "equipment"):
        if documents.get(key): result[key] = array(key)
    return result


def validate_documents(documents: dict, identifier: str) -> dict[str, list[dict]]:
    groups = document_groups(documents)
    owners = groups["classes"] + groups["races"] + groups.get("backgrounds", [])
    if not any(groups.values()):
        raise ClassBuilderError("Пустой пакет контента.")
    external = documents.get("external_classes", [])
    if not isinstance(external, list) or any(not isinstance(x, str) or x not in STANDARD_CLASSES for x in external):
        raise ClassBuilderError("external_classes: массив точных identifier стандартных классов D&D.")
    if len(external) != len(set(external)):
        raise ClassBuilderError("external_classes содержит повторения.")
    seen_ids, seen_identifiers = set(), set()
    local = {}
    for pack, items in groups.items():
        for item in items:
            if not isinstance(item, dict):
                raise ClassBuilderError("Документ должен быть объектом.")
            kind, item_id = item.get("type"), str(item.get("_id", ""))
            if kind not in {"classes": {"class", "subclass"}, "races": {"race"}, "backgrounds": {"background"}, "features": {"feat"}, "spells": {"spell"}, "feats": {"feat"}, "equipment": {"weapon", "equipment", "consumable", "tool", "loot"}}[pack]:
                raise ClassBuilderError(f"Недопустимый тип в {pack}: {kind}.")
            if not DOCUMENT_ID.fullmatch(item_id) or item_id in seen_ids:
                raise ClassBuilderError(f"Некорректный или повторяющийся _id: {item_id}.")
            seen_ids.add(item_id)
            slug = item.get("system", {}).get("identifier", "")
            # Один identifier подкласса в рамках этого пакета; будущая библиотека может содержать несколько классов.
            identity = (kind, slug)
            if not slug or identity in seen_identifiers:
                raise ClassBuilderError(f"Пустой или повторяющийся identifier: {identity}.")
            seen_identifiers.add(identity)
            local[f"Compendium.{identifier}.{pack}.Item.{item_id}"] = item
    parents = {item["system"]["identifier"]: item for item in groups["classes"] if item["type"] == "class"}
    subclasses = [i for i in groups["classes"] if i["type"] == "subclass"]
    if set(parents) & set(external):
        raise ClassBuilderError("Класс не может быть одновременно локальным и внешним.")
    for item in subclasses:
        parent = parents.get(item["system"].get("classIdentifier"))
        if parent is None:
            if item["system"].get("classIdentifier") in external:
                continue
            raise ClassBuilderError(f"Подкласс {item['name']}: class_identifier не совпадает с identifier класса; стандартный класс объявите в external_classes.")
        if not any(a.get("type") == "Subclass" for a in parent["system"].get("advancement", {}).values()):
            raise ClassBuilderError("Класс с подклассами требует Subclass advancement на уровне выбора.")
    edges = {}
    pattern = re.compile(r"Compendium\." + re.escape(identifier) + r"\.[A-Za-z0-9_-]+\.Item\.[A-Za-z0-9]+")
    for uuid, item in local.items():
        refs = set()
        for value in walk_strings(item):
            refs.update(pattern.findall(value))
            if value.startswith(("feature:", "feat:", "spell:")):
                raise ClassBuilderError(f"Неразрешённая ссылка {value}.")
            if value.startswith(f"Compendium.{identifier}."):
                refs.add(value)
        for ref in refs:
            if ref not in local:
                raise ClassBuilderError(f"Ссылка на отсутствующий документ: {ref}.")
        edges[uuid] = refs
    # Class spell libraries are owned by existing class metadata, independently
    # of optional player-facing HTML catalogues. This validates membership only:
    # it does not grant, prepare or add the spell to a character.
    class_roots = {i["system"]["identifier"]: u for u, i in local.items() if i["type"] == "class"}
    for spell_uuid, item in local.items():
        if item["type"] != "spell":
            continue
        conversion = item.get("flags", {}).get("warcraft-conversion", {})
        owner = conversion.get("class")
        if isinstance(owner, str) and owner in class_roots and isinstance(conversion.get("original_spell"), str) and conversion["original_spell"].strip():
            edges[class_roots[owner]].add(spell_uuid)
    reachable = set()
    pending = [u for u, i in local.items() if i["type"] in {"class", "subclass", "race", "background"} or u.split(".")[2] == "feats" or (i["type"] == "spell" and documents.get("library_spells") is True)]
    while pending:
        u = pending.pop()
        if u in reachable:
            continue
        reachable.add(u)
        pending.extend(edges[u] - reachable)
    unused = [i["name"] for u, i in local.items() if i["type"] in {"feat", "spell"} and u not in reachable and u.split(".")[2] != "feats" and not (i["type"] == "spell" and (i.get("flags", {}).get("warcraft-conversion", {}).get("chapterReviewed") is True or (i.get("flags", {}).get("warcraft-conversion", {}).get("requiresRuling") is True and not i.get("system", {}).get("activities")) or (i.get("flags", {}).get("wow-dnd5e", {}).get("sharedSpell") is True and i.get("flags", {}).get("wow-dnd5e", {}).get("originalSpell") and not i.get("system", {}).get("ability") and not i.get("system", {}).get("sourceItem") and not i.get("flags", {}).get("warcraft-conversion", {}).get("class"))))]
    if unused:
        raise ClassBuilderError("Особенности не связаны с классом/подклассом/расой: " + ", ".join(unused))
    return groups
