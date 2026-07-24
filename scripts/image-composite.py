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
    method = args.method
    if method not in COMPOSITE_METHODS:
        print(f"ERROR: Unknown method '{method}'. Choose from: {list(COMPOSITE_METHODS.keys())}", file=sys.stderr)
        return 1

    # Resolve inputs
    input_files = resolve_inputs(args.inputs)
    if len(input_files) < 2:
        print(f"ERROR: Need at least 2 input files. Found {len(input_files)}.", file=sys.stderr)
        return 1

    print(f"Compositing {len(input_files)} scenes using '{method}' method...")

    # Read all scenes
    scenes = []
    profiles = []
    reference_profile = None

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
    return 0


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
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommand")

    # composite
    p_comp = subparsers.add_parser("composite", help="Create composite from multiple scenes")
    p_comp.add_argument("--inputs", nargs="+", required=True, help="Input GeoTIFF files")
    p_comp.add_argument("--output", required=True, help="Output composite path")
    p_comp.add_argument(
        "--method", default="median",
        choices=["median", "mean", "maxNDVI", "minRed"],
        help="Compositing method (default: median)",
    )
    p_comp.add_argument("--cloud-mask", help="Optional cloud mask file")

    # cloud-mask
    p_mask = subparsers.add_parser("cloud-mask", help="Apply cloud mask")
    p_mask.add_argument("--input", required=True, help="Input GeoTIFF file")
    p_mask.add_argument("--qa-band", help="QA band name or index")
    p_mask.add_argument("--threshold", type=float, default=0.3, help="Cloud threshold (0-1, default 0.3)")
    p_mask.add_argument("--output", required=True, help="Output masked file path")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "composite":
        return cmd_composite(args)
    elif args.command == "cloud-mask":
        return cmd_cloud_mask(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
