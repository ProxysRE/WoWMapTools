"""Smoke tests for first Void Crypt scene; real WoW ZIP render is a separate QA gate."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image

from wowmap.foundry import compile_scene, uid
from wowmap.render import render, resource_names, validate
from wowmap.structures import wall_parts


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "examples" / "void-crypt-entrance.json"


class VoidCryptEntranceTests(unittest.TestCase):
    def load(self):
        return json.loads(PLAN.read_text(encoding="utf-8"))

    def test_schema_dimensions_and_terrain_dependencies(self):
        plan = self.load()
        self.assertEqual(validate(plan), (3200, 2400))
        self.assertEqual(plan["foundry"]["key"], "crypt-entrance")
        self.assertEqual(plan["export_format"], "webp")
        self.assertFalse(plan["foundry"]["global_light"])
        self.assertGreaterEqual(len(plan["objects"]), 24)
        self.assertGreaterEqual(len(plan["walls"]), 20)
        self.assertGreaterEqual(len(plan["details"]), 40)
        self.assertTrue(all(path.endswith(".blp") for path in resource_names(plan)))
        self.assertTrue(all(o["model"].endswith(".m2") for o in plan["objects"]))

    def test_entrances_and_side_rooms_remain_open(self):
        plan = self.load()
        walls = {w["id"]: w for w in plan["walls"]}
        for key, opening in [
            ("facade-north", "front-arch"),
            ("hall-north-center", "vestibule-into-hall"),
            ("hall-west", "west-memorial-entry"),
            ("hall-east", "east-crypt-entry"),
            ("hall-south", "descent-entrance"),
            ("stair-end", "stairs-descend"),
        ]:
            _, parts = wall_parts(walls[key])
            self.assertIn(opening, [entry["id"] for _, _, entry in parts])
        self.assertFalse(walls["east-niche-east"]["openings"])
        self.assertFalse(walls["west-niche-west"]["openings"])
        ids = [w["id"] for w in plan["walls"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_foundry_regions_link_to_next_scene(self):
        plan = self.load()
        scene = compile_scene(
            plan, "void-crypt", "crypt-entrance",
            {"crypt-entrance": {"to-passages", "arrival-from-passages"},
             "crypt-passages": {"arrival-from-entrance"}},
            "wowmap/void-crypt/crypt-entrance",
            has_overhead=True,
        )
        self.assertEqual(scene["grid"]["size"], 80)
        self.assertEqual(scene["grid"]["distance"], 5)
        self.assertEqual(len(scene["lights"]), 5)
        self.assertEqual(len(scene["regions"]), 2)
        region = next(r for r in scene["regions"] if r["flags"]["wowmap"]["sourceId"] == "to-passages")
        system = region["behaviors"][0]["system"]
        dest = ("Scene." + uid("void-crypt", "crypt-passages")
                + ".Region." + uid("void-crypt", "crypt-passages", "region", "arrival-from-entrance"))
        self.assertEqual(system["destination"], dest)
        self.assertEqual(sum(1 for w in scene["walls"] if w["door"]), 0)
        self.assertTrue(any(t["texture"]["src"].endswith("overhead.webp") for t in scene["tiles"]))

    def test_low_resolution_synthetic_render(self):
        # Test compositor geometry without distributing copyrighted WoW imagery.
        # Real M2 rendering is tested separately against the private ZIPs.
        plan = self.load()
        plan["pixels_per_cell"] = 16
        plan["objects"] = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = root / "assets"
            files = assets / "files"
            files.mkdir(parents=True)
            records = []
            for idx, source in enumerate(sorted(resource_names(plan))):
                name = f"material-{idx}.png"
                Image.new("RGB", (16, 16), (35 + idx * 20, 65 + idx * 13, 78 + idx * 11)).save(files / name)
                records.append({"id": f"test:{idx}", "source": source,
                                "file": f"files/{name}"})
            (assets / "catalog.json").write_text(json.dumps({"records": records}), encoding="utf-8")
            out = root / "render"
            metadata = render(plan, assets, out)
            self.assertEqual((metadata["width"], metadata["height"]), (640, 480))
            self.assertTrue((out / "map-vtt.webp").is_file())
            self.assertTrue((out / "scene-geometry.json").is_file())
            self.assertFalse((out / "map-grid.png").exists())
            geom = json.loads((out / "scene-geometry.json").read_text())
            self.assertTrue(any(p["type"] == "passage" and p["id"] == "front-arch"
                                for p in geom["elements"]))


if __name__ == "__main__":
    unittest.main()
