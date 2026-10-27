"""Integration checks for all three Void Crypt plans (synthetic graphics only).

This is a static navigation check, not a Foundry browser/gameplay test.
Openable doors are treated as traversable. Decorative M2 footprints are not
assumed to be blockers; final map QA needs the source model geometry.
"""
import json
import math
from collections import deque
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image
from wowmap.foundry import compile_scene, uid
from wowmap.render import render, resource_names, validate

ROOT = Path(__file__).resolve().parents[1]
KEYS = ("crypt-entrance", "crypt-passages", "crypt-sanctum")
FILES = [ROOT / "examples" / ("void-" + key + ".json") for key in KEYS]
# The leading "void-" maps to the canonical names void-crypt-entrance,
# void-crypt-passages, and void-crypt-sanctum.


def load_plans():
    return {key: json.loads(file.read_text(encoding="utf-8"))
            for key, file in zip(KEYS, FILES)}


def make_nav_mask(plan, compiled, step=.25, clearance=.43):
    """Rasterized walkability: floor coverage minus solid wall/barrier envelopes."""
    w, h = plan["size_cells"]
    ys, xs = np.mgrid[step / 2:h:step, step / 2:w:step]
    occupied = np.zeros(xs.shape, dtype=bool)
    # All three undercrypt floors consist of rectangles and ellipses.
    for floor in plan.get("floors", []):
        shape = floor["shape"]
        a, b, c, d = shape["bounds"]
        if shape["type"] == "rectangle":
            occupied |= (xs >= a) & (xs < c) & (ys >= b) & (ys < d)
        elif shape["type"] == "ellipse":
            occupied |= ((xs - (a + c) / 2) / ((c - a) / 2)) ** 2 + \
                        ((ys - (b + d) / 2) / ((d - b) / 2)) ** 2 < 1
        else:
            raise AssertionError("Unexpected floor shape in crypt QA")
    for wall in compiled["walls"]:
        if wall["door"] or wall["move"] == 0:
            continue  # Opens without a key/puzzle; do not lock the route.
        x1, y1, x2, y2 = [v / plan["pixels_per_cell"] for v in wall["c"]]
        dx, dy = x2 - x1, y2 - y1
        length_sq = dx * dx + dy * dy
        t = np.clip(((xs-x1)*dx + (ys-y1)*dy)/length_sq, 0, 1)
        occupied &= ((xs - (x1 + t*dx))**2 + (ys - (y1 + t*dy))**2) > clearance**2
    return occupied, step


def path_exists(mask, step, start, end, excluded=None):
    def index(xy):
        x, y = xy
        return int(y/step), int(x/step)
    a, b = index(start), index(end)
    if not (mask[a] and mask[b]):
        return False
    todo = deque([a])
    seen = {a}
    h, w = mask.shape
    while todo:
        y, x = todo.popleft()
        if (y, x) == b:
            return True
        for dy, dx in ((0,1),(1,0),(0,-1),(-1,0)):
            ny, nx = y+dy, x+dx
            if not (0 <= ny < h and 0 <= nx < w and mask[ny,nx]):
                continue
            if excluded and excluded((nx+.5)*step, (ny+.5)*step):
                continue
            if (ny,nx) not in seen:
                seen.add((ny,nx)); todo.append((ny,nx))
    return False


class VoidCryptBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plans = load_plans()
        cls.regions = {k:{r["id"] for r in p["foundry"]["regions"]}
                       for k,p in cls.plans.items()}
        cls.compiled = {
            k: compile_scene(p, "void-crypt", k, cls.regions,
                             "wowmap/void-crypt/"+k, has_overhead=any(
                                 o.get("layer") == "overhead" for o in p.get("objects", [])))
            for k,p in cls.plans.items()
        }

    def test_schema_and_stress_limits(self):
        for key, size in [("crypt-entrance", (40,30)),
                          ("crypt-passages", (72,40)),
                          ("crypt-sanctum", (36,36))]:
            plan = self.plans[key]
            self.assertEqual(plan["foundry"]["key"], key)
            self.assertEqual(plan["size_cells"], list(size))
            self.assertEqual(validate(plan), (size[0]*80,size[1]*80))
            self.assertLessEqual(size[0]*size[1]*80*80, 20_000_000)
            self.assertEqual(plan["export_format"], "webp")
            self.assertEqual(self.compiled[key]["grid"]["size"], 80)
            self.assertFalse(plan["foundry"]["global_light"])
        self.assertEqual(self.compiled["crypt-passages"]["width"], 5760)
        self.assertEqual(self.compiled["crypt-passages"]["height"], 3200)

    def test_all_four_foundry_transitions_are_resolved(self):
        expected = {
            ("crypt-entrance","to-passages"):("crypt-passages","arrival-from-entrance"),
            ("crypt-passages","to-entrance"):("crypt-entrance","arrival-from-passages"),
            ("crypt-passages","to-sanctum"):("crypt-sanctum","arrival-from-passages"),
            ("crypt-sanctum","to-passages"):("crypt-passages","arrival-from-sanctum"),
        }
        actual = {}
        for key, scene in self.compiled.items():
            for region in scene["regions"]:
                source_id = region["flags"]["wowmap"]["sourceId"]
                if not region["behaviors"]:
                    continue
                self.assertEqual(len(region["behaviors"]), 1)
                behavior = region["behaviors"][0]
                self.assertEqual(behavior["type"], "teleportToken")
                actual[(key,source_id)] = behavior["system"]["destination"]
        self.assertEqual(set(actual), set(expected))
        for source, (dest_scene,dest_region) in expected.items():
            self.assertEqual(actual[source], "Scene." + uid("void-crypt",dest_scene)
                             + ".Region." + uid("void-crypt",dest_scene,"region",dest_region))
        for key,plan in self.plans.items():
            zones=[r for r in plan["foundry"]["regions"] if r["id"].startswith("arrival")]
            self.assertTrue(zones)
            # Arrival regions contain no teleport triggers: no immediate return.
            self.assertTrue(all(not z.get("behaviors") for z in zones))

    def test_passages_two_routes_and_all_waypoints(self):
        scene = self.compiled["crypt-passages"]
        self.assertGreaterEqual(len(scene["walls"]), 60)
        self.assertEqual(len(scene["lights"]), 16)
        mask,step=make_nav_mask(self.plans["crypt-passages"],scene)
        start,end=(6,21),(68,21)
        for name,pos in [
            ("branch",(29,22)), ("north chapel",(50,14)), ("south chambers",(51,30)),
            ("merged exit",(61,21)), ("sacristy",(61,9)), ("ossuary",(12,31)),
            ("northern niche",(22,12)), ("collapsed chapel",(44,7)), ("south dead-end",(25,35))
        ]:
            self.assertTrue(path_exists(mask,step,start,pos), name)
        self.assertTrue(path_exists(mask,step,start,end))
        # Removing either optional circuit still leaves one valid way around the collapse.
        self.assertTrue(path_exists(mask,step,start,end,
                        excluded=lambda x,y: 34<=x<=58 and y<=21), "Southern detour")
        self.assertTrue(path_exists(mask,step,start,end,
                        excluded=lambda x,y: 34<=x<=58 and y>=26), "Northern detour")

    def test_sanctum_reachable_and_boss_center_unobstructed(self):
        plan=self.plans["crypt-sanctum"]
        compiled=self.compiled["crypt-sanctum"]
        self.assertEqual(len(plan["foundry"]["barriers"]),4)
        self.assertGreaterEqual(len(compiled["walls"]),55)
        mask,step=make_nav_mask(plan,compiled)
        start=(7,18)
        for name,end in [
            ("boss reserve",(21,18)), ("far edge",(28,18)),
            ("north flank",(21,11)), ("south flank",(21,25))
        ]:
            self.assertTrue(path_exists(mask,step,start,end),name)
        for obj in plan["objects"]:
            self.assertGreater(math.dist(obj["position"],[21,18]), 4.5)
        # Central 3x3 boss space has no solid wall segments or pillar barriers.
        for xx in (20,21,22):
            for yy in (17,18,19):
                self.assertTrue(mask[int(yy/step),int(xx/step)],(xx,yy))

    def test_native_door_count(self):
        self.assertEqual(sum(1 for w in self.compiled["crypt-passages"]["walls"]
                             if w["door"] == 1), 2)

    def test_synthetic_compositor_on_extended_and_round_scene(self):
        """Check pipeline at 16px per cell without access to private WoW assets."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets=root/"assets"
            (assets/"files").mkdir(parents=True)
            all_assets=sorted(set().union(*(resource_names(self.plans[k])
                                            for k in ("crypt-passages","crypt-sanctum"))))
            entries=[]
            for n,source in enumerate(all_assets):
                dest=f"test-{n}.png"
                Image.new("RGB",(16,16),
                          (45+((n*41)%120),58+((n*31)%110),78+((n*17)%120))).save(assets/"files"/dest)
                entries.append({"id":f"test:{n}","source":source,"file":"files/"+dest})
            (assets/"catalog.json").write_text(json.dumps({"records":entries}),encoding="utf-8")
            for key in ("crypt-passages","crypt-sanctum"):
                plan=json.loads(json.dumps(self.plans[key]))
                plan["pixels_per_cell"]=16
                plan["objects"]=[]
                out=root/key
                result=render(plan,assets,out)
                self.assertTrue((out/"map-vtt.webp").exists(),key)
                self.assertTrue((out/"scene-geometry.json").exists(),key)
                self.assertFalse((out/"map-grid.png").exists(),key)
                self.assertEqual(result["width"], plan["size_cells"][0]*16)
                self.assertEqual(result["height"],plan["size_cells"][1]*16)


if __name__ == "__main__":
    unittest.main()
