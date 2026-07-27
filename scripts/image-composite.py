#!/usr/bin/env python3
"""
Image Composite CLI — Multi-temporal image compositing with cloud masking.

Privacy Notice:
    ALL processing is local. No data is uploaded or transmitted anywhere.
    This tool only reads from and writes to your local filesystem.

Data Source:
    Local GeoTIFF files (no download required).

License: MIT-0
Author: ruiduobao
Version: 0.1.0
"""

import argparse
import glob
import json
import sys
import os
from typing import List, Optional, Tuple

try:
    import numpy as np
except ImportError:
    print("ERROR: 'numpy' is required. Install with: pip install numpy")
    sys.exit(1)

try:
    import rasterio
    from rasterio.transform import from_bounds
except ImportError:
    print("ERROR: 'rasterio' is required. Install with: pip install rasterio numpy")
    sys.exit(1)

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None  # type: ignore


# ============================================================
# Place resolver (v0.2.0 — batch2 upgrade)
# ============================================================

def _resolve_place(place: str):
    """Resolve a Chinese place name to bbox + centroid."""
    import os
    import sys

    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "..", "_shared"),
        os.path.join(os.getcwd(), "_shared"),
    ]
    for c in candidates:
        full = os.path.abspath(c)
        if os.path.isdir(full) and os.path.isfile(os.path.join(full, "place_resolver.py")):
            if full not in sys.path:
                sys.path.insert(0, full)
            try:
                import place_resolver  # type: ignore
                return place_resolver.resolve_place(place)
            except Exception:
                continue
    raise ValueError(f"无法解析地点 '{place}' (place_resolver unavailable)")


# ============================================================
# Presets (v0.2.0)
# ============================================================

COMPOSITE_PRESETS = {
    "ndvi-trend": {
        "method": "maxNDVI",
        "description": "maxNDVI 合成（取 NDVI 最高的像元），适合多时相植被指数合成",
    },
    "cloud-free": {
        "method": "median",
        "description": "中值合成（去除云污染），适合光学影像时间序列",
    },
    "shadow-free": {
        "method": "minRed",
        "description": "minRed 合成（取 Red 最小的像元），去除云阴影",
    },
    "average": {
        "method": "mean",
        "description": "均值合成，平衡各时相贡献",
    },
}


def resolve_inputs(input_patterns: List[str]) -> List[str]:
    """Resolve input file patterns to actual file paths."""
    files = []
    for pattern in input_patterns:
        if os.path.isfile(pattern):
            files.append(pattern)
        else:
            matched = glob.glob(pattern)
            files.extend(matched)
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for f in files:
        abs_path = os.path.abspath(f)
        if abs_path not in seen:
            seen.add(abs_path)
            unique.append(f)
    return unique


def read_raster(filepath: str) -> Tuple[np.ndarray, dict]:
    """Read a raster file and return data + profile."""
    with rasterio.open(filepath) as src:
        data = src.read().astype(np.float64)
        profile = src.profile.copy()
        nodata = src.nodata
    return data, profile, nodata


def apply_cloud_mask(data: np.ndarray, mask: np.ndarray, nodata: float = np.nan) -> np.ndarray:
    """Apply cloud mask to data. Masked pixels set to nodata."""
    result = data.copy()
    result[mask == 1] = nodata
    return result


def detect_cloud_threshold(data: np.ndarray, threshold: float = 0.3) -> np.ndarray:
    """Simple cloud detection based on reflectance threshold."""
    # Use first few bands for cloud detection
    mean_reflectance = np.nanmean(data[:3], axis=0)
    # Normalize if needed
    max_val = np.nanmax(mean_reflectance)
    if max_val > 0:
        mean_reflectance = mean_reflectance / max_val
    cloud_mask = (mean_reflectance > threshold).astype(np.uint8)
    return cloud_mask


def compute_ndvi(data: np.ndarray, profile: dict) -> np.ndarray:
    """Compute NDVI from raster data. Auto-detects Landsat/Sentinel bands."""
    # Try to detect bands based on count and profile
    n_bands = data.shape[0]

    if n_bands >= 4:
        # Standard: band 3 = Red, band 4 = NIR (Landsat 8/9 style)
        # Sentinel-2: band 3 = Red, band 4 = NIR (in 4-band composites)
        red = data[3].astype(np.float64)
        nir = data[4].astype(np.float64) if n_bands > 4 else data[3].astype(np.float64)

        # If only 4 bands, assume B,G,R,NIR order (Sentinel-2 4-band)
        if n_bands == 4:
            red = data[2].astype(np.float64)
            nir = data[3].astype(np.float64)
    else:
        # Fallback: use last two bands
        red = data[-2].astype(np.float64)
        nir = data[-1].astype(np.float64)

    denominator = nir + red
    ndvi = np.where(denominator != 0, (nir - red) / denominator, 0.0)
    return ndvi


def composite_median(stack: np.ndarray, nodata: float = np.nan) -> np.ndarray:
    """Median composite along the first axis (scene axis)."""
    with np.errstate(all="ignore"):
        result = np.nanmedian(stack, axis=0)
    return result


def composite_mean(stack: np.ndarray, nodata: float = np.nan) -> np.ndarray:
    """Mean composite along the first axis."""
    with np.errstate(all="ignore"):
        result = np.nanmean(stack, axis=0)
    return result


def composite_max_ndvi(stack: np.ndarray, profiles: list) -> np.ndarray:
    """maxNDVI composite: for each pixel, pick the scene with highest NDVI."""
    n_scenes = stack.shape[0]
    ndvi_stack = []
    for i in range(n_scenes):
        ndvi = compute_ndvi(stack[i], profiles[i] if i < len(profiles) else {})
        ndvi_stack.append(ndvi)
    ndvi_stack = np.array(ndvi_stack)

    # Find index of max NDVI for each pixel
    with np.errstate(all="ignore"):
        best_indices = np.nanargmax(ndvi_stack, axis=0)  # (height, width)

    # Select pixels from best scene
    n_bands = stack.shape[1]
    height, width = best_indices.shape
    result = np.empty((n_bands, height, width), dtype=stack.dtype)
    for b in range(n_bands):
        result[b] = stack[best_indices, b, np.arange(height)[:, None], np.arange(width)]
    return result


def composite_min_red(stack: np.ndarray, nodata: float = np.nan) -> np.ndarray:
    """minRed composite: for each pixel, pick the scene with lowest red band."""
    # Use band index 2 (red) if available, else band 0
    red_idx = min(2, stack.shape[1] - 1)
    red_stack = stack[:, red_idx, :, :]

    with np.errstate(all="ignore"):
        best_indices = np.nanargmin(red_stack, axis=0)  # (height, width)

    # Select from each band the pixel from the best scene
    n_bands = stack.shape[1]
    height, width = best_indices.shape
    result = np.empty((n_bands, height, width), dtype=stack.dtype)
    for b in range(n_bands):
        result[b] = stack[best_indices, b, np.arange(height)[:, None], np.arange(width)]
    return result


COMPOSITE_METHODS = {
    "median": composite_median,
    "mean": composite_mean,
    "maxNDVI": composite_max_ndvi,
    "minRed": composite_min_red,
}


def cmd_composite(args: argparse.Namespace) -> int:
    """Handle the 'composite' subcommand."""
    # Resolve preset
    if args.preset:
        ps = COMPOSITE_PRESETS[args.preset]
        method = ps["method"]
        print(f"[preset] {args.preset}: {ps['description']}")
    else:
        method = args.method or "median"

    if method not in COMPOSITE_METHODS:
        print(f"ERROR: Unknown method '{method}'. Choose from: {list(COMPOSITE_METHODS.keys())}", file=sys.stderr)
        return 1

    # Resolve inputs: --inputs OR --input-dir
    if args.input_dir:
        from pathlib import Path
        d = Path(args.input_dir)
        # Case-insensitive scan: get all .tif/.tiff regardless of case
        seen = set()
        files = []
        for pat in ("*.tif", "*.tiff", "*.TIF", "*.TIFF"):
            for p in d.glob(pat):
                key = str(p).lower()
                if key not in seen:
                    seen.add(key)
                    files.append(p)
        files.sort()
        if not files:
            print(f"ERROR: No GeoTIFF files in {d}", file=sys.stderr)
            return 1
        input_files = [str(p) for p in files]
    else:
        if not args.inputs:
            print("ERROR: Provide --inputs or --input-dir", file=sys.stderr)
            return 1
        input_files = resolve_inputs(args.inputs)

    if len(input_files) < 2:
        print(f"ERROR: Need at least 2 input files. Found {len(input_files)}.", file=sys.stderr)
        return 1

    print(f"Compositing {len(input_files)} scenes using '{method}' method...")

    # Read all scenes
    scenes = []
    profiles = []
    reference_profile = None
    skipped = []

    iterator = tqdm(input_files, desc="Reading") if tqdm else input_files
    for filepath in iterator:
        try:
            data, profile, nodata = read_raster(filepath)
            scenes.append(data)
            profiles.append(profile)
            if reference_profile is None:
                reference_profile = profile
        except Exception as e:
            print(f"WARNING: Skipping {filepath}: {e}", file=sys.stderr)
            skipped.append(filepath)
            continue

    if len(scenes) < 2:
        print("ERROR: Not enough valid scenes to composite.", file=sys.stderr)
        return 1

    # Normalize shapes: find common shape and crop/pad
    min_bands = min(s.shape[0] for s in scenes)
    min_height = min(s.shape[1] for s in scenes)
    min_width = min(s.shape[2] for s in scenes)

    # Stack with common shape
    normalized = [s[:min_bands, :min_height, :min_width] for s in scenes]
    stack = np.array(normalized)

    # Replace nodata with nan for processing
    for i, scene in enumerate(normalized):
        nodata_val = profiles[i].get("nodata")
        if nodata_val is not None:
            stack[i][scene == nodata_val] = np.nan

    # Apply cloud mask if provided
    if args.cloud_mask:
        try:
            mask_data, _, _ = read_raster(args.cloud_mask)
            if mask_data.shape[1:] == (min_height, min_width):
                cloud_mask = mask_data[0] > 0
                for i in range(stack.shape[0]):
                    for b in range(stack.shape[1]):
                        stack[i, b][cloud_mask] = np.nan
                print("Applied cloud mask.")
        except Exception as e:
            print(f"WARNING: Could not apply cloud mask: {e}", file=sys.stderr)

    # Compute composite
    print(f"Computing {method} composite...")
    composite_fn = COMPOSITE_METHODS[method]
    result = composite_fn(stack, profiles)

    # Replace nan with 0 for output
    result = np.nan_to_num(result, nan=0.0)

    # Write output
    output_path = args.output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    # --format dispatch (batch-D). Default 'auto' = geotiff.
    fmt = getattr(args, "format", "auto")
    if fmt == "auto":
        fmt_resolved = "geotiff"
    else:
        fmt_resolved = fmt

    if fmt_resolved == "geotiff":
        out_profile = reference_profile.copy()
        out_profile.update({
            "height": min_height,
            "width": min_width,
            "count": min_bands,
            "dtype": result.dtype,
        })
        with rasterio.open(output_path, "w", **out_profile) as dst:
            dst.write(result)
        print(f"Wrote composite to {output_path} ({min_bands} bands, {min_width}x{min_height})")
    elif fmt_resolved == "png":
        # Render an 8-bit PNG preview: use the first three bands, scale to 0-255.
        try:
            from PIL import Image
        except ImportError:
            print("ERROR: --format=png requires Pillow. Install with: pip install pillow",
                  file=sys.stderr)
            return 1
        # Pick the first 3 bands (RGB). If only 1 band available, replicate.
        n = min(3, result.shape[0])
        rgb = result[:n].astype("float32")
        # If less than 3 bands, broadcast to 3
        if n < 3:
            rgb = np.broadcast_to(rgb[:1], (3,) + rgb.shape[1:]).copy()
        # Normalize to 0-255 per band
        rgb8 = np.zeros_like(rgb, dtype="uint8")
        for i in range(3):
            band = rgb[i]
            lo = float(np.nanmin(band))
            hi = float(np.nanmax(band))
            if hi > lo:
                rgb8[i] = ((band - lo) / (hi - lo) * 255).astype("uint8")
            else:
                rgb8[i] = np.zeros_like(band, dtype="uint8")
        # rasterio stores (bands, H, W); PIL expects (H, W, bands)
        arr = np.transpose(rgb8, (1, 2, 0))
        img = Image.fromarray(arr, mode="RGB")
        img.save(output_path, format="PNG")
        print(f"Wrote PNG preview to {output_path} ({min_width}x{min_height})")
    else:
        print(f"ERROR: Unknown --format: {fmt_resolved}", file=sys.stderr)
        return 1

    # QA summary (v0.2.0)
    if getattr(args, "qa", False):
        qa_path = os.path.splitext(output_path)[0] + ".qa.json"
        qa = {
            "method": method,
            "preset": getattr(args, "preset", None),
            "n_input_files": len(input_files),
            "n_valid_scenes": len(scenes),
            "n_skipped": len(skipped),
            "skipped_files": skipped,
            "bands": min_bands,
            "width": min_width,
            "height": min_height,
            "crs": str(reference_profile.get("crs", "")),
            "transform": list(reference_profile.get("transform", [0, 0, 0, 0, 0, 0])),
            "input_files": [os.path.basename(f) for f in input_files],
            "output": output_path,
        }
        with open(qa_path, "w", encoding="utf-8") as f:
            json.dump(qa, f, indent=2, ensure_ascii=False)
        print(f"  QA summary: {qa_path}")

    return 0


def cmd_from_place(args: argparse.Namespace) -> int:
    """One-line composite: --place + --date + --dataset → fetch + composite + QA.

    [PHASE 1+ 2026-07-26 REFACTOR]
    此子命令现在通过两步串联实现：
    1. 用本 skill 的 _geoskill_core.aoi 解析 --place → bbox
    2. subprocess 调 landsat-download / sentinel-downloader 拉场景
    3. 调本 skill 的 cmd_composite 合成

    替代之前依赖的 _shared/from_stac.py（Phase 0 已删）。

    Example
    -------
    image-composite from-place \\
        --place 成都市 \\
        --start-date 2024-06-01 --end-date 2024-08-31 \\
        --dataset landsat-c2-l2 \\
        --max-cloud 20 \\
        --method median \\
        --output chengdu_summer_median.tif \\
        --qa
    """
    import os as _os
    import sys as _sys
    import subprocess as _sp
    import json as _json

    # Step 1: 用本 skill vendored 的 _geoskill_core.aoi 解析 place
    skill_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    gk_dir = _os.path.join(skill_dir, "_geoskill_core")
    if not _os.path.isdir(gk_dir):
        print("ERROR: _geoskill_core not vendored in this skill. Run vendor.py.",
              file=sys.stderr)
        return 3
    # 用包式 import（让相对导入 .manifest 等能工作）
    if skill_dir not in _sys.path:
        _sys.path.insert(0, skill_dir)
    try:
        from _geoskill_core import aoi as _aoi
    except Exception as _e:
        print(f"ERROR: failed to import _geoskill_core.aoi: {_e}", file=sys.stderr)
        return 3
    try:
        m = _aoi.resolve_place(
            args.place, allow_nominatim=not args.no_nominatim, use_cache=False
        )
    except Exception as _e:
        print(f"ERROR: failed to resolve --place={args.place!r}: {_e}", file=sys.stderr)
        return 5
    bbox = m.bbox_wgs84
    if not bbox or len(bbox) != 4:
        print(f"ERROR: invalid bbox from resolve_place: {bbox}", file=sys.stderr)
        return 5
    print(f"[from-place] resolved {args.place!r} → bbox={bbox} (resolver={m.resolver})",
          file=sys.stderr)

    # Step 2: 决定调用哪个 fetch skill
    # - sentinel-* dataset → sentinel-downloader
    # - landsat-* / default → landsat-download
    dataset = args.dataset or "landsat-c2-l2"
    fetch_skill = "sentinel-downloader" if "sentinel" in dataset.lower() else "landsat-download"
    # 找 fetch skill 目录（同级）
    parent_dir = _os.path.dirname(skill_dir)
    fetch_skill_dir = _os.path.join(parent_dir, fetch_skill)
    # 找 fetch script（多种命名约定）
    candidates = [
        _os.path.join(fetch_skill_dir, f"{fetch_skill}.py"),
        _os.path.join(fetch_skill_dir, f"{fetch_skill.split('-')[0]}-download.py"),  # sentinel-download.py
        _os.path.join(fetch_skill_dir, "scripts", f"{fetch_skill}.py"),
        _os.path.join(fetch_skill_dir, "scripts", f"{fetch_skill.replace('-', '_')}.py"),
        _os.path.join(fetch_skill_dir, f"{fetch_skill.replace('-', '_')}.py"),
    ]
    fetch_script = None
    for cand in candidates:
        if _os.path.isfile(cand):
            fetch_script = cand
            break
    if fetch_script is None:
        print(f"ERROR: fetch skill script not found. Tried: {candidates}", file=sys.stderr)
        return 3
    cache_dir = _os.path.join(_os.path.dirname(args.output) or ".", ".from_place_cache")
    _os.makedirs(cache_dir, exist_ok=True)
    # 不同 fetch skill 的 --bbox 参数格式不同
    # - landsat-download: --bbox W S E N (4 个 float, no subcommand)
    # - sentinel-download: --bbox W S E N (4 个 float, nargs=4, no subcommand)
    # 统一传 4 个 float；landsat 用 --max-cloud-cover，sentinel 用 --max-cloud
    max_cloud_flag = "--max-cloud" if fetch_skill == "sentinel-downloader" else "--max-cloud-cover"
    cmd = [
        _sys.executable, fetch_script,
        "--bbox", str(bbox[0]), str(bbox[1]), str(bbox[2]), str(bbox[3]),
        "--start-date", args.start_date,
        "--end-date", args.end_date,
        max_cloud_flag, str(args.max_cloud),
        "--output-dir", cache_dir,
    ]
    if args.limit and args.limit > 0:
        cmd += ["--limit", str(args.limit)]
    if hasattr(args, "pick_best") and args.pick_best:
        cmd += ["--pick-best"]
    print(f"[from-place] invoking: {' '.join(cmd)}", file=sys.stderr)
    try:
        r = _sp.run(cmd, capture_output=True, text=True, timeout=600)
    except _sp.TimeoutExpired:
        print("ERROR: fetch skill timeout after 600s", file=sys.stderr)
        return 4
    except Exception as _e:
        print(f"ERROR: fetch skill failed to start: {_e}", file=sys.stderr)
        return 7
    if r.returncode != 0:
        print(f"ERROR: fetch skill exit {r.returncode}:\n{r.stderr[-500:]}",
              file=sys.stderr)
        return r.returncode
    # 找 fetch 产物（*.tif 在 cache_dir 下）
    input_files = []
    for root, _, files in _os.walk(cache_dir):
        for f in files:
            if f.endswith(".tif") and not f.endswith(".part"):
                input_files.append(_os.path.join(root, f))
    if not input_files:
        print(f"ERROR: no .tif produced in {cache_dir}", file=sys.stderr)
        return 5
    print(f"[from-place] fetched {len(input_files)} scene(s)", file=sys.stderr)

    # Step 3: 调 cmd_composite
    composite_args = argparse.Namespace(
        inputs=input_files,
        output=args.output,
        method=args.method,
        normalize=False,
        nodata=None,
        cloud_mask=None,
        qa=args.qa,
    )
    rc = cmd_composite(composite_args)
    if rc == 0 and not args.keep_cache:
        # 清理 cache
        try:
            import shutil as _sh
            _sh.rmtree(cache_dir, ignore_errors=True)
        except Exception:
            pass
    return rc


def cmd_cloud_mask(args: argparse.Namespace) -> int:
    """Handle the 'cloud-mask' subcommand."""
    input_path = args.input
    output_path = args.output
    threshold = args.threshold

    if not os.path.isfile(input_path):
        print(f"ERROR: File '{input_path}' not found.", file=sys.stderr)
        return 1

    if not (0 <= threshold <= 1):
        print("ERROR: --threshold must be between 0 and 1.", file=sys.stderr)
        return 1

    try:
        with rasterio.open(input_path) as src:
            data = src.read().astype(np.float64)
            profile = src.profile.copy()
            nodata = src.nodata

        # Detect clouds
        cloud_mask = detect_cloud_threshold(data, threshold)
        cloud_pct = np.mean(cloud_mask) * 100

        # Apply mask
        masked_data = apply_cloud_mask(data, cloud_mask, nodata if nodata is not None else 0)

        print(f"Cloud coverage: {cloud_pct:.1f}%")

        # Write output
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(masked_data.astype(profile["dtype"]))

        print(f"Wrote masked file to {output_path}")
        return 0

    except Exception as e:
        print(f"ERROR: Cloud masking failed: {e}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="image-composite",
        description="Multi-temporal image compositing with cloud masking.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Cloud-free median composite (uses default fixtures/inputs)
  image-composite composite --inputs scene1.tif scene2.tif --output comp.tif --preset cloud-free

  # maxNDVI composite for vegetation trend
  image-composite composite --inputs *.tif --output ndvi_max.tif --preset ndvi-trend --qa

Presets:
  ndvi-trend   - maxNDVI 合成，适合多时相植被指数合成
  cloud-free   - median 合成，去除云污染
  shadow-free  - minRed 合成，去除云阴影
  average      - mean 合成
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommand")

    # composite
    p_comp = subparsers.add_parser("composite", help="Create composite from multiple scenes")
    p_comp.add_argument("--inputs", nargs="+", help="Input GeoTIFF files (or glob)")
    p_comp.add_argument("--input-dir", help="Directory of GeoTIFFs (alternative to --inputs)")
    p_comp.add_argument("--place", help="Place name; not used directly here, see auto-fetch")
    p_comp.add_argument("--preset", choices=list(COMPOSITE_PRESETS.keys()),
                        help="Use a preset configuration (overrides --method)")
    p_comp.add_argument("--output", required=True, help="Output composite path")
    p_comp.add_argument(
        "--method", default=None,
        choices=["median", "mean", "maxNDVI", "minRed"],
        help="Compositing method (default: median; ignored if --preset)",
    )
    p_comp.add_argument("--cloud-mask", help="Optional cloud mask file")
    p_comp.add_argument(
        "--format", choices=["auto", "geotiff", "png"], default="auto",
        help="Output format (default: auto = geotiff; png = 8-bit RGB/NDVI preview).",
    )
    p_comp.add_argument("--qa", action="store_true", help="Write QA summary JSON next to the output")

    # cloud-mask
    p_mask = subparsers.add_parser("cloud-mask", help="Apply cloud mask")
    p_mask.add_argument("--input", required=True, help="Input GeoTIFF file")
    p_mask.add_argument("--qa-band", help="QA band name or index")
    p_mask.add_argument("--threshold", type=float, default=0.3, help="Cloud threshold (0-1, default 0.3)")
    p_mask.add_argument("--output", required=True, help="Output masked file path")
    p_mask.add_argument("--qa", action="store_true", help="Write QA summary JSON next to the output")

    # from-place: 一句话完成"下载 + 合成"（via _shared/from_stac.py）
    p_fp = subparsers.add_parser(
        "from-place",
        help="One-line composite: --place + --start-date + --dataset → fetch + composite + QA. "
             "Requires: pip install planetary-computer pystac-client rasterio.",
    )
    p_fp.add_argument("--place", required=True, help="行政区名 (中文/English) → bbox")
    p_fp.add_argument("--start-date", required=True, help="开始日期 YYYY-MM-DD")
    p_fp.add_argument("--end-date", required=True, help="结束日期 YYYY-MM-DD")
    p_fp.add_argument("--dataset", default="sentinel-2-l2a",
                      choices=["sentinel-2-l2a", "landsat-c2-l2"],
                      help="STAC collection (default sentinel-2-l2a)")
    p_fp.add_argument("--bands", nargs="+", default=["B02", "B03", "B04", "B08"],
                      help="Asset keys (default B02 B03 B04 B08 = S2 RGB+NIR)")
    p_fp.add_argument("--max-cloud", type=float, default=20.0,
                      help="最大云量%% (default 20)")
    p_fp.add_argument("--limit", type=int, default=5, help="最多取几景 (default 5)")
    p_fp.add_argument("--method", default="median",
                      choices=["median", "mean", "max-ndvi", "min-red"],
                      help="合成方法 (default median)")
    p_fp.add_argument("--output", required=True, help="合成输出 GeoTIFF 路径")
    p_fp.add_argument("--cache-dir", default="./from_stac_cache",
                      help="下载缓存目录 (default ./from_stac_cache)")
    p_fp.add_argument("--no-nominatim", action="store_true",
                      help="跳过 Nominatim（只用 Open-Meteo 解析地名）")
    p_fp.add_argument("--qa", action="store_true", help="写出 QA JSON")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "composite":
        return cmd_composite(args)
    elif args.command == "cloud-mask":
        return cmd_cloud_mask(args)
    elif args.command == "from-place":
        return cmd_from_place(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
