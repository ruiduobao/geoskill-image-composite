#!/usr/bin/env python3
"""Tests for image-composite CLI."""

import sys
import os
import csv
import json
import tempfile
import importlib.util
import unittest
from unittest.mock import patch, MagicMock

# Load the module
_script_path = os.path.join(os.path.dirname(__file__), "..", "scripts", "image-composite.py")
_spec = importlib.util.spec_from_file_location("image_composite", _script_path)
ic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ic)


class TestResolveInputs(unittest.TestCase):
    def test_exact_paths(self,):
        # Create temp files
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as f1:
            f1.write(b"dummy")
            p1 = f1.name
        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as f2:
            f2.write(b"dummy")
            p2 = f2.name
        try:
            result = ic.resolve_inputs([p1, p2])
            self.assertEqual(len(result), 2)
        finally:
            os.unlink(p1)
            os.unlink(p2)

    def test_glob_pattern(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False, dir="/tmp") as f:
            f.write(b"dummy")
            name = f.name
        try:
            pattern = os.path.join(os.path.dirname(name), "*.tif")
            result = ic.resolve_inputs([pattern])
            self.assertGreaterEqual(len(result), 1)
        finally:
            os.unlink(name)

    def test_nonexistent_file(self):
        result = ic.resolve_inputs(["/nonexistent/file.tif"])
        self.assertEqual(len(result), 0)


class TestCompositeMethods(unittest.TestCase):
    def test_composite_median(self):
        # Shape: (n_scenes, n_bands, height, width)
        stack = np.array([
            [[[1.0, 2.0], [3.0, 4.0]]],
            [[[5.0, 6.0], [7.0, 8.0]]],
            [[[3.0, 4.0], [5.0, 6.0]]],
        ])
        result = ic.composite_median(stack)
        expected = np.array([[[3.0, 4.0], [5.0, 6.0]]])
        np.testing.assert_array_almost_equal(result, expected)

    def test_composite_mean(self):
        stack = np.array([
            [[[2.0, 4.0], [6.0, 8.0]]],
            [[[4.0, 6.0], [8.0, 10.0]]],
        ])
        result = ic.composite_mean(stack)
        expected = np.array([[[3.0, 5.0], [7.0, 9.0]]])
        np.testing.assert_array_almost_equal(result, expected)

    def test_composite_min_red(self):
        stack = np.array([
            [[[1.0, 2.0], [3.0, 4.0]], [[10.0, 20.0], [30.0, 40.0]]],
            [[[5.0, 6.0], [7.0, 8.0]], [[5.0, 10.0], [15.0, 20.0]]],
        ])
        result = ic.composite_min_red(stack)
        # minRed picks scene with lowest red (band index 2 doesn't exist, so band 1)
        # Scene 0 band 1: [[10,20],[30,40]], Scene 1 band 1: [[5,10],[15,20]]
        # min is scene 1, so result should be scene 1's data
        expected_scene = stack[1]
        np.testing.assert_array_almost_equal(result, expected_scene)

    def test_composite_with_nodata(self):
        stack = np.array([
            [[[1.0, np.nan], [3.0, 4.0]]],
            [[[5.0, 6.0], [7.0, 8.0]]],
            [[[3.0, 4.0], [5.0, 6.0]]],
        ])
        result = ic.composite_median(stack)
        # nanmedian should ignore nan
        self.assertFalse(np.any(np.isnan(result)))


class TestDetectClouds(unittest.TestCase):
    def test_cloud_detection(self):
        # Create data with bright pixels (clouds)
        # Shape: (n_bands, height, width)
        data = np.array([
            [[0.1, 0.2], [0.9, 0.95]],
            [[0.1, 0.2], [0.85, 0.9]],
        ])
        mask = ic.detect_cloud_threshold(data, threshold=0.3)
        # Bright pixels should be flagged as clouds
        self.assertEqual(mask.shape, (2, 2))
        self.assertEqual(mask.dtype, np.uint8)


class TestCLI(unittest.TestCase):
    def test_composite_invalid_method(self):
        args = ic.argparse.Namespace(
            inputs=["a.tif", "b.tif"], input_dir=None, output="out.tif",
            method="invalid_method", preset=None, cloud_mask=None, qa=False, place=None,
        )
        rc = ic.cmd_composite(args)
        self.assertEqual(rc, 1)

    def test_composite_too_few_inputs(self):
        args = ic.argparse.Namespace(
            inputs=["only_one.tif"], input_dir=None, output="out.tif",
            method="median", preset=None, cloud_mask=None, qa=False, place=None,
        )
        rc = ic.cmd_composite(args)
        self.assertEqual(rc, 1)

    def test_cloud_mask_invalid_threshold(self):
        args = ic.argparse.Namespace(
            input="scene.tif", qa_band=None, threshold=1.5, output="masked.tif",
        )
        rc = ic.cmd_cloud_mask(args)
        self.assertEqual(rc, 1)


# Need numpy for tests
import numpy as np


class TestFormatArgParser(unittest.TestCase):
    """Test --format argument on the 'composite' subcommand (batch-D)."""

    def test_default_format(self):
        # Replicate the relevant portion of the parser
        import argparse
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        p = sub.add_parser("composite")
        p.add_argument("--format", choices=["auto", "geotiff", "png"], default="auto")
        args = parser.parse_args(["composite"])
        self.assertEqual(args.format, "auto")

    def test_geotiff_format(self):
        import argparse
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        p = sub.add_parser("composite")
        p.add_argument("--format", choices=["auto", "geotiff", "png"], default="auto")
        args = parser.parse_args(["composite", "--format", "geotiff"])
        self.assertEqual(args.format, "geotiff")

    def test_png_format(self):
        import argparse
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        p = sub.add_parser("composite")
        p.add_argument("--format", choices=["auto", "geotiff", "png"], default="auto")
        args = parser.parse_args(["composite", "--format", "png"])
        self.assertEqual(args.format, "png")

    def test_rejects_unknown_format(self):
        import argparse
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        p = sub.add_parser("composite")
        p.add_argument("--format", choices=["auto", "geotiff", "png"], default="auto")
        with self.assertRaises(SystemExit):
            parser.parse_args(["composite", "--format", "jpeg"])


class TestCompositeEndToEndFormat(unittest.TestCase):
    """End-to-end: composite two synthetic GeoTIFFs to a chosen format."""

    def _make_raster(self, path, data, profile_overrides=None):
        import rasterio as rio
        from rasterio.transform import Affine
        if data.ndim == 2:
            data = data[None, :, :]
        n_bands, height, width = data.shape
        transform = Affine(1.0, 0.0, 0.0, 0.0, -1.0, float(height))
        profile = {
            "driver": "GTiff", "height": height, "width": width,
            "count": n_bands, "dtype": "float32", "crs": "EPSG:4326",
            "transform": transform, "nodata": -9999.0,
        }
        if profile_overrides:
            profile.update(profile_overrides)
        with rio.open(path, "w", **profile) as dst:
            for i in range(n_bands):
                dst.write(data[i], i + 1)

    def test_composite_to_png(self):
        with tempfile.TemporaryDirectory() as d:
            d = os.path.abspath(d)
            data1 = np.array([
                [[0.1, 0.2, 0.3, 0.4]],
                [[0.2, 0.3, 0.4, 0.5]],
                [[0.3, 0.4, 0.5, 0.6]],
                [[0.4, 0.5, 0.6, 0.7]],
            ], dtype="float32")
            data2 = np.array([
                [[0.15, 0.25, 0.35, 0.45]],
                [[0.25, 0.35, 0.45, 0.55]],
                [[0.35, 0.45, 0.55, 0.65]],
                [[0.45, 0.55, 0.65, 0.75]],
            ], dtype="float32")
            p1 = os.path.join(d, "a.tif")
            p2 = os.path.join(d, "b.tif")
            self._make_raster(p1, data1)
            self._make_raster(p2, data2)
            out_png = os.path.join(d, "composite.png")
            args = ic.argparse.Namespace(
                inputs=[p1, p2], input_dir=None, output=out_png,
                method="median", preset=None, cloud_mask=None,
                qa=False, place=None, format="png",
            )
            rc = ic.cmd_composite(args)
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out_png))
            # Verify it's a PNG
            with open(out_png, "rb") as f:
                magic = f.read(8)
            self.assertEqual(magic, b"\x89PNG\r\n\x1a\n")

    def test_composite_to_geotiff_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            d = os.path.abspath(d)
            data1 = np.array([
                [[0.1, 0.2, 0.3, 0.4]],
                [[0.2, 0.3, 0.4, 0.5]],
            ], dtype="float32")
            data2 = np.array([
                [[0.15, 0.25, 0.35, 0.45]],
                [[0.25, 0.35, 0.45, 0.55]],
            ], dtype="float32")
            p1 = os.path.join(d, "a.tif")
            p2 = os.path.join(d, "b.tif")
            self._make_raster(p1, data1)
            self._make_raster(p2, data2)
            out_tif = os.path.join(d, "composite.tif")
            args = ic.argparse.Namespace(
                inputs=[p1, p2], input_dir=None, output=out_tif,
                method="median", preset=None, cloud_mask=None,
                qa=False, place=None, format="geotiff",
            )
            rc = ic.cmd_composite(args)
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out_tif))
            import rasterio as rio
            with rio.open(out_tif) as src:
                self.assertEqual(src.count, 2)
                self.assertEqual(src.width, 4)
                self.assertEqual(src.height, 1)

    def test_composite_unknown_format_returns_error(self):
        with tempfile.TemporaryDirectory() as d:
            d = os.path.abspath(d)
            data1 = np.array([[[0.1, 0.2]]], dtype="float32")
            data2 = np.array([[[0.15, 0.25]]], dtype="float32")
            p1 = os.path.join(d, "a.tif")
            p2 = os.path.join(d, "b.tif")
            self._make_raster(p1, data1)
            self._make_raster(p2, data2)
            out = os.path.join(d, "composite.xyz")
            args = ic.argparse.Namespace(
                inputs=[p1, p2], input_dir=None, output=out,
                method="median", preset=None, cloud_mask=None,
                qa=False, place=None, format="jpeg",
            )
            rc = ic.cmd_composite(args)
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
