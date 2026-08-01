---
name: image-composite
description: 'Multi-temporal image compositing from local GeoTIFF files. Supports median, mean,  maxNDVI, and minRed compositing methods with cloud masking. Works on Landsat and  Sentinel-2 band naming conventions.  '
---

# Image Composite

Create multi-temporal image composites from local GeoTIFF files. Supports cloud
masking and multiple compositing methods. Works with Landsat and Sentinel-2 data.

## Features

- Median, mean, maxNDVI, and minRed compositing
- Cloud masking via QA band or threshold
- Landsat and Sentinel-2 band naming support
- Handles multiple input files with progress reporting

## Requirements

```bash
pip install rasterio numpy tqdm
```

## Usage

```bash
# Median composite of multiple scenes
python scripts\image-composite.py composite --inputs scene1.tif scene2.tif scene3.tif --output composite.tif

# Mean composite
python scripts\image-composite.py composite --inputs *.tif --method mean --output mean_composite.tif

# maxNDVI composite (best vegetation)
python scripts\image-composite.py composite --inputs *.tif --method maxNDVI --output ndvi_composite.tif

# Cloud masking
python scripts\image-composite.py cloud-mask --input scene.tif --threshold 0.3 --output masked.tif
```

## Installation

```bash
pip install rasterio numpy tqdm
# Or: pip install -r scripts/requirements.txt
```

## Parameters

### `composite`
| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--inputs` | Yes | — | Input GeoTIFF files (2+) |
| `--output` | Yes | — | Output composite path |
| `--method` | No | median | Compositing method: median, mean, maxNDVI, minRed |
| `--cloud-mask` | No | — | Optional cloud mask file |

### `cloud-mask`
| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--input` | Yes | — | Input GeoTIFF file |
| `--qa-band` | No | — | QA band name or index |
| `--threshold` | No | 0.3 | Cloud threshold (0-1) |
| `--output` | Yes | — | Output masked file |

## Data Source

- **Input**: Local GeoTIFF files (no download)
- **Processing**: 100% local

### maxNDVI Pixel Selection

The `maxNDVI` method selects, for each pixel position, the scene that has the **highest NDVI value** at that location. This produces a composite with the greenest, healthiest vegetation — ideal for creating cloud-free, maximum vegetation composites. NDVI is calculated as `(NIR - Red) / (NIR + Red)`.

### Band Requirements by Method

| Method | Required Bands | Description |
|--------|---------------|-------------|
| `median` | Any | Median of all valid pixels |
| `mean` | Any | Mean of all valid pixels |
| `maxNDVI` | Red + NIR | Selects pixel with highest NDVI |
| `minRed` | Red | Selects pixel with lowest red reflectance |

### Handling Mismatched Extents/Resolutions

- **Same extent, same resolution**: Direct compositing (default)
- **Different resolution**: Auto-reproject to finest resolution using nearest-neighbor
- **Different extent**: Intersection of all extents (output covers overlapping area only)
- **Different CRS**: Auto-reproject to first input's CRS
- Use `--target-crs` and `--target-resolution` to override

### QA Band Format (Landsat QA_PIXEL)

The QA_PIXEL band uses bit flags for cloud/shadow detection:

| Bit | Name | Value | Description |
|-----|------|-------|-------------|
| 0 | Fill | 0/1 | Fill data |
| 1 | Dilated Cloud | 0/1 | Dilated cloud |
| 2 | Cirrus | 0/1 | Cirrus (Landsat 8/9) |
| 3 | Cloud | 0/1 | Cloud |
| 4 | Cloud Shadow | 0/1 | Cloud shadow |
| 5 | Snow | 0/1 | Snow |
| 6 | Clear | 0/1 | Clear |
| 7 | Water | 0/1 | Water |

- Cloud-free pixels: bits 3-4 are `0`
- Use `--qa-bit 3` to mask clouds, `--qa-bit 3,4` for cloud + shadow

### Memory Management

- For large scenes (>2GB each), process in sequential mode with `--sequential`
- Use `--max-memory 4096` to limit RAM usage (MB)
- Close other applications when compositing many high-res scenes
- Output is written incrementally to reduce peak memory

### Output Data Type

- Default: preserves source data type (e.g., uint16 stays uint16)
- Specify with `--dtype`: `uint8`, `uint16`, `float32`
- Use `--dtype float32` for methods requiring decimal precision (mean, median)

### Landsat / Sentinel-2 Band Mapping

| Band | Landsat 8/9 | Sentinel-2 |
|------|-------------|------------|
| Blue | SR_B2 | B2 |
| Green | SR_B3 | B3 |
| Red | SR_B4 | B4 |
| NIR | SR_B5 | B8 |
| SWIR1 | SR_B6 | B11 |
| SWIR2 | SR_B7 | B12 |
| QA_PIXEL | QA_PIXEL | SCL (Scene Classification) |

### Nodata Handling

- Source nodata values are excluded from compositing
- Output nodata: same as first input's nodata value
- Use `--nodata VALUE` to set custom nodata
- Pixels with nodata in ALL scenes remain nodata in output

## Visualization

- Quick preview: `rasterio.plot.show(composite, cmap='terrain')`
- RGB composite: stack Red/Green/Blue bands with `matplotlib`
- NDVI visualization: `plt.imshow(ndvi, cmap='RdYlGn', vmin=-1, vmax=1)`
- Side-by-side comparison: use `matplotlib` subplots for before/after
- Export to PNG: `rasterio.plot.show(out_file='preview.png')`

## Troubleshooting

| Error | Cause | Solution |
|-------|-------|----------|
| `ConnectionError` | Network issue | Check internet, retry |
| `HTTP 429` | Rate limit | Wait 60s, retry |
| `ValueError` | Invalid input | Check parameter format |
| Empty output | No data | Try different parameters |
| `ModuleNotFoundError` | Missing dep | Run pip install |
| `MemoryError` | Too many scenes | Use `--sequential` or `--max-memory` |
| `CRSError` | CRS mismatch | Use `--target-crs` to unify |
| Band not found | Wrong naming | Check band mapping table above |

## Citation

If you use this tool in your research, please cite the input data sources (e.g., USGS Landsat, ESA Sentinel-2) and acknowledge the compositing methodology:

```bibtex
@software{image_composite_2024,
  author = {ruiduobao},
  title = {Image Composite Tool},
  year = {2024},
  note = {Multi-temporal image compositing for Landsat/Sentinel-2}
}
```

For Landsat data: "Landsat data are provided by the U.S. Geological Survey and/or the National Aeronautics and Space Administration."
For Sentinel-2 data: "Copernicus Sentinel data [2024] processed by ESA."

---

## Advanced Usage

### Weekly Composite Pipeline
```bash
# Composite all scenes from a week
python scripts\image-composite.py composite   --images S2A_20230101.tif S2A_20230105.tif S2A_20230110.tif   --method maxNDVI --sensor sentinel2   --output composite_week1.tif
```

### CI/CD Integration (GitHub Actions)
```yaml
# .github/workflows/weekly-composite.yml
name: Weekly Image Composite
on:
  schedule:
    - cron: '0 12 * * 1'  # Every Monday at 12:00
jobs:
  composite:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install numpy rasterio
      - run: |
          python scripts\image-composite.py composite \
            --images data/scenes/*.tif \
            --method maxNDVI --sensor sentinel2 \
            --output data/composite_$(date +%Y%m%d).tif
```

### Zonal Statistics with rasterio + GeoPandas
```python
import rasterio
import geopandas as gpd
from rasterio.features import geometry_mask

with rasterio.open('composite.tif') as src:
    img = src.read(1)
    profile = src.profile

# Compute zonal stats for polygons
gdf = gpd.read_file('aoi.gdf')
```

### Performance Tips
- Use `--max-memory` to limit RAM usage for large scenes
- `--sequential` mode reads one band at a time (slower but memory-safe)
- Mismatched extents are handled by intersection; use `--reference` to control output grid

---

## 中文说明

从本地 GeoTIFF 文件创建多时相影像合成。支持云掩膜和多种合成方法。兼容 Landsat 和 Sentinel-2 数据。

### 功能

- 中位数、平均值、最大 NDVI、最小红波段合成
- 通过 QA 波段或阈值进行云掩膜
- 支持 Landsat 和 Sentinel-2 波段命名
- 多文件输入带进度报告

### 依赖

```bash
pip install rasterio numpy tqdm
```

### 使用方法

```bash
# 中位数合成
python scripts\image-composite.py composite --inputs scene1.tif scene2.tif scene3.tif --output composite.tif

# 平均值合成
python scripts\image-composite.py composite --inputs *.tif --method mean --output mean_composite.tif

# 最大 NDVI 合成（最佳植被）
python scripts\image-composite.py composite --inputs *.tif --method maxNDVI --output ndvi_composite.tif

# 云掩膜
python scripts\image-composite.py cloud-mask --input scene.tif --threshold 0.3 --output masked.tif
```

### 数据来源

- **输入**: 本地 GeoTIFF 文件（无下载）
- **处理**: 完全本地

### maxNDVI 像素选择说明

`maxNDVI` 方法在每个像素位置选择 **NDVI 值最高** 的场景。这样生成的合成影像具有最绿、最健康的植被——适合创建无云、最大植被覆盖的合成影像。NDVI 计算公式: `(NIR - Red) / (NIR + Red)`。

### 各合成方法的波段需求

| 方法 | 所需波段 | 描述 |
|------|----------|------|
| `median` | 任意 | 所有有效像素的中位数 |
| `mean` | 任意 | 所有有效像素的平均值 |
| `maxNDVI` | 红 + 近红外 | 选择 NDVI 最高的像素 |
| `minRed` | 红波段 | 选择红反射率最低的像素 |

### 不匹配范围/分辨率的处理

- **相同范围、相同分辨率**: 直接合成（默认）
- **不同分辨率**: 使用最近邻法自动重投影到最高分辨率
- **不同范围**: 所有范围的交集（输出仅覆盖重叠区域）
- **不同坐标系**: 自动重投影到第一个输入的 CRS
- 使用 `--target-crs` 和 `--target-resolution` 覆盖默认行为

### QA 波段格式 (Landsat QA_PIXEL)

QA_PIXEL 波段使用位标志进行云/阴影检测:

| 位 | 名称 | 值 | 描述 |
|----|------|-----|------|
| 0 | Fill | 0/1 | 填充数据 |
| 1 | Dilated Cloud | 0/1 | 膨胀云 |
| 2 | Cirrus | 0/1 | 卷云（Landsat 8/9） |
| 3 | Cloud | 0/1 | 云 |
| 4 | Cloud Shadow | 0/1 | 云阴影 |
| 5 | Snow | 0/1 | 雪 |
| 6 | Clear | 0/1 | 晴空 |
| 7 | Water | 0/1 | 水体 |

- 无云像素: 位 3-4 为 `0`
- 使用 `--qa-bit 3` 掩膜云，`--qa-bit 3,4` 掩膜云+阴影

### 内存管理

- 大场景（>2GB/个）使用 `--sequential` 顺序处理
- 使用 `--max-memory 4096` 限制内存使用（MB）
- 合成多个高分辨率场景时关闭其他应用程序
- 输出增量写入以降低峰值内存

### 输出数据类型

- 默认: 保留源数据类型（如 uint16 保持 uint16）
- 使用 `--dtype` 指定: `uint8`, `uint16`, `float32`
- 需要小数精度的方法（mean, median）使用 `--dtype float32`

### Landsat / Sentinel-2 波段映射表

| 波段 | Landsat 8/9 | Sentinel-2 |
|------|-------------|------------|
| 蓝 | SR_B2 | B2 |
| 绿 | SR_B3 | B3 |
| 红 | SR_B4 | B4 |
| 近红外 | SR_B5 | B8 |
| 短波红外1 | SR_B6 | B11 |
| 短波红外2 | SR_B7 | B12 |
| QA_PIXEL | QA_PIXEL | SCL (场景分类) |

### 无数据值处理

- 合成时排除源 nodata 值
- 输出 nodata: 与第一个输入的 nodata 值相同
- 使用 `--nodata VALUE` 设置自定义 nodata
- 所有场景中均为 nodata 的像素在输出中仍为 nodata

### 可视化

- 快速预览: `rasterio.plot.show(composite, cmap='terrain')`
- RGB 合成: 使用 `matplotlib` 堆叠 Red/Green/Blue 波段
- NDVI 可视化: `plt.imshow(ndvi, cmap='RdYlGn', vmin=-1, vmax=1)`
- 并排比较: 使用 `matplotlib` subplots 显示前后对比
- 导出 PNG: `rasterio.plot.show(out_file='preview.png')`

### 故障排除

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| `ConnectionError` | 网络问题 | 检查网络，重试 |
| `HTTP 429` | 速率限制 | 等待 60 秒后重试 |
| `ValueError` | 无效输入 | 检查参数格式 |
| 空输出 | 无数据 | 尝试不同参数 |
| `ModuleNotFoundError` | 缺少依赖 | 运行 pip install |
| `MemoryError` | 场景过多 | 使用 `--sequential` 或 `--max-memory` |
| `CRSError` | 坐标系不匹配 | 使用 `--target-crs` 统一 |
| 波段未找到 | 命名错误 | 查看上方波段映射表 |
