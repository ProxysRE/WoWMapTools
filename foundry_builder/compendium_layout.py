"""Детерминированные папки компендиумов без зависимости от сеттинга."""
from copy import deepcopy
import hashlib
import json
import re

NAMES = {"barbarian": "Варвар", "bard": "Бард", "cleric": "Жрец", "druid": "Друид",
         "fighter": "Воин", "monk": "Монах", "paladin": "Паладин", "ranger": "Следопыт",
         "rogue": "Плут", "sorcerer": "Чародей", "warlock": "Колдун", "wizard": "Волшебник"}


def ownership_paths(groups):
    docs = {d["_id"]: d for values in groups.values() for d in values}
    edges = {key: set(re.findall(r"Compendium\.[\w-]+\.[\w-]+\.Item\.([A-Za-z0-9]{16})", json.dumps(d))) & docs.keys()
             for key, d in docs.items()}
    owners = {}
    for key, d in docs.items():
        kind = d.get("type")
        if kind not in {"class", "subclass", "race", "background"}:
            continue
        system = d.get("system", {})
        if kind == "race":
            path = ("Расовые особенности", d["name"])
        elif kind == "background":
            path = ("Предыстории", d["name"])
        else:
            identifier = system.get("classIdentifier") or system.get("identifier", "")
            path = (NAMES.get(identifier, d["name"]),)
        pending, seen = list(edges[key]), set()
        while pending:
            target = pending.pop()
            if target in seen:
                continue
            seen.add(target)
            owners.setdefault(target, set()).add(path)
            pending.extend(edges[target] - seen)
    return owners


def organize(documents, pack, kind="Item", ownership=None, link_lists=False):
    docs, folders = deepcopy(documents), {}

    def folder(path):
        parent = None
        for index, label in enumerate(path):
            key = tuple(path[:index + 1])
            if key not in folders:
                fid = hashlib.sha256((pack + "/" + "/".join(key)).encode()).hexdigest()[:16]
                folders[key] = {"_id": fid, "name": label, "type": kind, "folder": parent,
                                "sorting": "a", "sort": 0, "color": None, "flags": {}, "_key": "!folders!" + fid}
            parent = folders[key]["_id"]
        return parent

    labels = {"classes": "Классы и подклассы", "races": "Расы", "backgrounds": "Предыстории",
              "features": "Общие особенности", "feats": "Черты", "equipment": "Снаряжение"}
    for d in docs:
        system = d.get("system", {})
        paths = (ownership or {}).get(d["_id"], set())
        if pack == "spells":
            level = system.get("level", 0)
            path = ["Заговоры" if not level else f"{level}-й круг"]
        elif pack == "classes" and d.get("type") == "subclass":
            parent = system.get("classIdentifier", "")
            path = [NAMES.get(parent, parent)]
        elif pack == "features" and len(paths) == 1:
            path = list(next(iter(paths)))
        else:
            path = [labels.get(pack, pack)]
        d["folder"] = folder(path)
    return docs, list(folders.values())
