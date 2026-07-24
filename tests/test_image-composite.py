#!/usr/bin/env python3
"""Tests for image-composite CLI."""

import sys
import os
import json
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
            inputs=["a.tif", "b.tif"], output="out.tif",
            method="invalid_method", cloud_mask=None,
        )
        rc = ic.cmd_composite(args)
        self.assertEqual(rc, 1)

    def test_composite_too_few_inputs(self):
        args = ic.argparse.Namespace(
            inputs=["only_one.tif"], output="out.tif",
            method="median", cloud_mask=None,
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


if __name__ == "__main__":
    unittest.main()
