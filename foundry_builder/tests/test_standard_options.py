"""Regression checks for setting-independent player content packages."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from background_builder import build_background
from class_builder import ClassBuilderError
from class_package_builder import build_package
from foundry_module_builder import ModuleBuilderError, prepare_documents
import builder_app


ROOT = Path(__file__).resolve().parents[1]


def source():
    return json.loads((ROOT / "examples/standard_options.json").read_text(encoding="utf-8"))


class StandardOptions(unittest.TestCase):
    def test_all_categories_and_stable_references_without_wow(self):
        raw = source()
        before = copy.deepcopy(raw)
        result = build_package(raw)
        self.assertEqual(raw, before)
        self.assertEqual(result, build_package(raw))
        packs = prepare_documents(result, module_id="independent-content")
        self.assertEqual(set(packs), {"classes", "races", "backgrounds", "features", "feats", "spells"})
        self.assertEqual([i["type"] for i in packs["classes"]], ["subclass"])
        self.assertEqual(packs["classes"][0]["system"]["classIdentifier"], "fighter")
        background = packs["backgrounds"][0]
        grant = next(a for a in background["system"]["advancement"].values() if a["type"] == "ItemGrant")
        self.assertEqual(grant["configuration"]["items"][0]["uuid"], f"Compendium.independent-content.feats.Item.{packs['feats'][0]['_id']}")
        self.assertNotIn("Compendium.standard-options.", json.dumps(packs))
        self.assertNotIn("wow-dnd5e", json.dumps(packs))
        self.assertTrue(packs["spells"][0]["system"]["activities"])
        self.assertNotIn("mechanics", packs["spells"][0])

    def test_standard_parent_must_be_explicit_and_valid(self):
        for external in ([], ["figther"], ["fighter", "fighter"], "fighter"):
            raw = source()
            raw["external_classes"] = external
            with self.subTest(external=external), self.assertRaises(ClassBuilderError):
                build_package(raw)

    def test_background_roundtrip_and_forbidden_advancements(self):
        raw = source()["backgrounds"][0]
        raw["advancement"] = raw["advancement"][:1]
        one = build_background(raw)[0]
        self.assertEqual(one, build_background(one)[0])
        self.assertEqual(one, builder_app.build_document("background", one).document)
        for advancement in ({"type": "hit_points"}, {"type": "size", "sizes": ["med"]},
                            {"type": "trait", "level": 1, "grants": ["skills:prc"]}):
            raw["advancement"] = [advancement]
            with self.subTest(advancement=advancement), self.assertRaises(ClassBuilderError):
                build_background(raw)

    def test_background_native_fields_are_preserved(self):
        raw = source()["backgrounds"][0]
        raw["advancement"] = raw["advancement"][:1]
        native = build_background(raw)[0]
        native["system"]["startingEquipment"] = [{"_id": "testEquipment001", "type": "linked", "key": "example"}]
        native["flags"]["third-party"] = {"keep": True}
        self.assertEqual(native, build_background(native)[0])

    def test_standalone_catalogues(self):
        for name in ("feats", "spells"):
            raw = {"schema_version": 4, "identifier": "catalogue", "rules": "2014", name: source()[name]}
            result = prepare_documents(build_package(raw), module_id="catalogue-module")
            self.assertEqual(set(result), {name})

    def test_background_only_with_feat_and_nested_feature(self):
        sample = source()
        raw = {key: sample[key] for key in ("schema_version", "identifier", "rules", "backgrounds", "feats")}
        raw["features"] = [sample["features"][1]]
        raw["feats"][0]["advancement"] = [{"type": "item_grant", "level": 0, "items": ["feature:heritage"]}]
        packs = prepare_documents(build_package(raw))
        self.assertEqual(set(packs), {"backgrounds", "feats", "features"})

    def test_broken_feat_and_orphan_feature_rejected(self):
        raw = source()
        raw["feats"] = []
        with self.assertRaises(ClassBuilderError):
            build_package(raw)
        raw = source()
        raw["features"].append(dict(raw["features"][0], key="feature:orphan"))
        with self.assertRaisesRegex(ClassBuilderError, "не связаны"):
            build_package(raw)

    def test_empty_package_and_pack_collisions(self):
        with self.assertRaises(ClassBuilderError):
            build_package({"schema_version": 4, "identifier": "empty"})
        for reserved in ("backgrounds", "feats", "equipment"):
            with self.subTest(reserved=reserved), self.assertRaises(ModuleBuilderError):
                prepare_documents(build_package(source()), feature_pack=reserved)

    def test_existing_external_uuid_survives(self):
        raw = source()
        uuid = "Compendium.some-installed-module.features.Item.1234567890abcdef"
        raw["backgrounds"][0]["advancement"].append({"type": "item_grant", "level": 0, "items": [uuid]})
        packs = prepare_documents(build_package(raw), module_id="target-module")
        self.assertIn(uuid, json.dumps(packs))

    def test_schema_three_still_rejects_new_fields(self):
        raw = source()
        raw["schema_version"] = 3
        with self.assertRaisesRegex(ClassBuilderError, "schema_version 4"):
            build_package(raw)


if __name__ == "__main__":
    unittest.main()
