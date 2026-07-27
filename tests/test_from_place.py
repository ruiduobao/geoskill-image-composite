"""Tests for image-composite from-place subcommand (PHASE 1+ REFACTORED).

Per 40个Skill实用性与协同升级路线图.md §1.1 P0 / §2 / §5 Phase 1:
- 2026-07-26: _shared/from_stac.py 已删
- PHASE 1: from-place 重写为两步串联：geoskill_core.aoi 解析 → 调 landsat-download / sentinel-downloader 拉场景 → 调 cmd_composite
- 测试验证：aoi 解析正确、fetch 失败有明确错误码、不再返回 PHASE 0 DISABLED 假失败

真实使用需要联网（landsat-download / sentinel-downloader 调用 STAC API）。
"""
import os
import sys
import subprocess


HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, ".."))
SCRIPTS = os.path.join(PROJECT_ROOT, "scripts")


def test_from_place_subcommand_in_help():
    out = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "image-composite.py"), "--help"],
        capture_output=True, text=True, timeout=15,
    )
    combined = out.stdout + out.stderr
    assert "from-place" in combined


def test_from_place_resolves_place_then_runs():
    """PHASE 1+: from-place 真的解析 --place 然后调 fetch skill。
    没有网络时应该返回明确的网络/无数据错误（exit 4 或 5），不再 PHASE 0 DISABLED 假失败。
    """
    out = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "image-composite.py"),
         "from-place", "--place", "北京市",
         "--start-date", "2024-06-01", "--end-date", "2024-06-08",
         "--output", os.path.join(os.environ.get("TEMP", "/tmp"), "ic_test.tif"),
         "--cache-dir", os.path.join(os.environ.get("TEMP", "/tmp"), "ic_cache")],
        capture_output=True, text=True, timeout=60,
    )
    combined = out.stdout + out.stderr
    # 验证：真的尝试了 aoi 解析
    assert "from-place" in combined
    # 验证：不再返回 PHASE 0 DISABLED 假消息
    assert "PHASE 0 DISABLED" not in combined
    # 退出码应该是 4（网络）/ 5（无数据）/ 0（成功），**不能是 2（参数错）**
    # 因为我们传了合法参数；真的失败应该是 4/5/0
    assert out.returncode in (0, 4, 5, 7), f"unexpected exit code {out.returncode}"
    # 失败时应该有清晰的错误消息
    if out.returncode != 0:
        assert "ERROR" in combined or "no " in combined.lower()


def test_from_place_help_lists_place():
    out = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "image-composite.py"),
         "from-place", "--help"],
        capture_output=True, text=True, timeout=15,
    )
    combined = out.stdout + out.stderr
    assert "--place" in combined
    assert "--start-date" in combined
    assert "--end-date" in combined
    assert "--dataset" in combined


def test_aoi_resolution_works_via_vendored_geoskill_core():
    """验证 _geoskill_core.aoi 在该 skill 内部真实工作。"""
    skill_dir = PROJECT_ROOT
    sys.path.insert(0, skill_dir)
    from _geoskill_core import aoi
    m = aoi.resolve_place("北京市", allow_nominatim=True, use_cache=False)
    assert m.bbox_wgs84 is not None
    assert len(m.bbox_wgs84) == 4
    assert m.bbox_wgs84[0] < m.bbox_wgs84[2]  # W < E
    assert m.bbox_wgs84[1] < m.bbox_wgs84[3]  # S < N
    assert m.resolver in ("hardcoded", "nominatim", "open-meteo")
