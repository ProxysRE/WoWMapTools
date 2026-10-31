"""Reproducible 3-scene Void Crypt build using the original WoW ZIP assets.

This is intentionally NOT an Actions hosted job: private Blizzard assets are
not in the GitHub repository and must be supplied to the local build.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from wowmap.foundry import compile_scene, export_bundle
from wowmap.models import RawAssets, inspect_model, preview
from wowmap.render import render, resource_names, validate

SCENES=("crypt-entrance","crypt-passages","crypt-sanctum")
PACKAGE_NAMES=tuple(row['file'] for row in json.loads((ROOT/'resources/void-crypt-r3-assets.json').read_text(encoding='utf-8'))['packages'])


def scene_file(key):
    return ROOT/"examples"/("void-"+key+".json")


def preflight(packages,package_id):
    plans={key:json.loads(scene_file(key).read_text(encoding="utf-8")) for key in SCENES}
    regions={key:{r["id"] for r in p.get("foundry",{}).get("regions",[])}
             for key,p in plans.items()}
    if any(len(regions[k])!=len(plans[k]["foundry"]["regions"]) for k in SCENES):
        raise ValueError("Duplicate Foundry region key")
    for key,plan in plans.items():
        validate(plan)
        if plan["foundry"]["key"]!=key:
            raise ValueError("Unexpected scene key "+key)
        compile_scene(plan,package_id,key,regions,"wowmap/"+package_id+"/"+key,
                      has_overhead=any(o.get("layer")=="overhead" for o in plan.get("objects",[])))
    if not Path(packages).is_dir():
        raise ValueError("ZIP package directory not found: "+str(packages))
    missing_packs=[name for name in PACKAGE_NAMES if not (Path(packages)/name).is_file()]
    if missing_packs:
        raise ValueError("Missing required WoW ZIP packages: "+", ".join(missing_packs))
    result={}
    with RawAssets(packages) as raw:
        for key,plan in plans.items():
            missing=set()
            for name in resource_names(plan):
                if not raw.has(name):
                    missing.add(name)
            models=sorted({o["model"] for o in plan.get("objects",[])})
            model_notes=[]
            for model in models:
                if not raw.has(model):
                    missing.add(model)
                    continue
                info=inspect_model(raw,model)
                missing.update(info["missing"])
                # Detect models with no visible top-facing triangles before long renders.
                # M2s consisting solely of vertical billboards cannot yield top-down sprites.
                try:
                    preview(raw, model, 96)
                except ValueError as error:
                    raise ValueError(key+": unrenderable top-down M2 "+model+": "+str(error)) from error
                if not info["inspection_complete"] or info["used_replaceable_texture_types"]:
                    model_notes.append({"model":model,
                                        "inspection_complete":info["inspection_complete"],
                                        "replaceable_textures":info["used_replaceable_texture_types"]})
            if missing:
                raise ValueError(key+": missing original WoW resources: "+", ".join(sorted(missing)))
            result[key]=dict(plan=str(scene_file(key).relative_to(ROOT)),
                             dimensions=plan["size_cells"],
                             pixels_per_cell=plan["pixels_per_cell"],
                             model_instances=len(plan.get("objects",[])),unique_models=len(models),
                             source_textures=len(resource_names(plan)),
                             warnings=model_notes)
    return plans,result


def archive_export(bundle,zip_path):
    """Only export finished Foundry products; never copy raw WotLK ZIP packages."""
    with ZipFile(zip_path,"w") as z:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                z.write(path,arcname=str(path.relative_to(bundle.parent)).replace("\\","/"),
                        compress_type=ZIP_STORED if path.suffix==".webp" else ZIP_DEFLATED)


def main(argv=None):
    ap=argparse.ArgumentParser(description="Render and export the linked three-scene Void Crypt")
    ap.add_argument("--packages",required=True,help="Folder containing the private WotLK ZIP packages listed in the asset manifest")
    ap.add_argument("--out",required=True,help="Working/output directory (must not contain a previous export)")
    ap.add_argument("--id",default="void-crypt",help="Unique Foundry bundle slug; default void-crypt")
    ap.add_argument("--preflight-only",action="store_true",help="Verify real texture/M2 dependencies and link schema without rendering")
    ap.add_argument("--visual-review",help="Author's reviewed appearance signatures; regenerate proofs before using")
    args=ap.parse_args(argv)
    try:
        start=time.perf_counter()
        work=Path(args.out).expanduser().resolve()
        export_path=work/("foundry-"+args.id)
        zip_path=work/("foundry-"+args.id+".zip")
        if not args.preflight_only and ((export_path.exists() and any(export_path.iterdir())) or zip_path.exists()):
            raise ValueError("Export already exists: use a new --id/--out (existing assets are never overwritten)")
        plans,checks=preflight(args.packages,args.id)
        if args.visual_review:
            from wowmap.review import review_plans,verify_decisions
            with RawAssets(args.packages) as raw:review=review_plans(plans,raw,work/'visual-review')
            verify_decisions(review,json.loads(Path(args.visual_review).read_text(encoding='utf-8-sig')))
        print(json.dumps({"status":"preflight_ok","checks":checks},ensure_ascii=False,indent=2),flush=True)
        if args.preflight_only:
            return 0
        output_dirs=[]
        stats={}
        for key,plan in plans.items():
            path=work/"rendered"/key
            t=time.perf_counter()
            print("Rendering",key,plan["size_cells"],flush=True)
            meta=render(plan,work/"_unused_assets_catalog",path,packages=args.packages)
            stats[key]=dict(seconds=round(time.perf_counter()-t,2),width=meta["width"],
                            height=meta["height"],objects=meta["object_count"])
            output_dirs.append(path)
        bundle=export_bundle(output_dirs,export_path,args.id)
        archive_export(export_path,zip_path)
        report={"status":"rendered_and_exported","package_id":args.id,"render":stats,
                "foundry":bundle,"archive":str(zip_path),"seconds":round(time.perf_counter()-start,2)}
        (work/("void-crypt-"+args.id+"-build-report.json")).write_text(
            json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 0
    except (OSError,ValueError,KeyError,RuntimeError) as error:
        print("ERROR: "+str(error),file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
