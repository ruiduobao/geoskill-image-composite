# Image Composite

Create multi-temporal image composites from local GeoTIFF files with cloud masking.

## Install

### ClawHub
```bash
clawhub install image-composite
```

### Manual
```bash
git clone https://github.com/ruiduobao/image-composite.git
cd image-composite
pip install rasterio numpy tqdm
```

### Claude Code / skills.sh
```bash
claude skills install image-composite
```

## Quick Start

```bash
# Median composite
python scripts/image-composite.py composite --inputs scene1.tif scene2.tif scene3.tif --output composite.tif

# Mean composite
python scripts/image-composite.py composite --inputs *.tif --method mean --output mean.tif

# Cloud masking
python scripts/image-composite.py cloud-mask --input scene.tif --threshold 0.3 --output masked.tif
```

## Data Source

- **Input**: Local GeoTIFF files
- **Processing**: 100% local, no data uploaded

---

# 遥感影像合成工具

从本地 GeoTIFF 文件创建多时相影像合成，支持云掩膜。

## 安装

### ClawHub
```bash
clawhub install image-composite
```

### 手动安装
```bash
git clone https://github.com/ruiduobao/image-composite.git
cd image-composite
pip install rasterio numpy tqdm
```

### Claude Code / skills.sh
```bash
claude skills install image-composite
```

## 快速开始

```bash
# 中位数合成
python scripts/image-composite.py composite --inputs scene1.tif scene2.tif scene3.tif --output composite.tif

# 平均值合成
python scripts/image-composite.py composite --inputs *.tif --method mean --output mean.tif

# 云掩膜
python scripts/image-composite.py cloud-mask --input scene.tif --threshold 0.3 --output masked.tif
```

## 数据来源

- **输入**: 本地 GeoTIFF 文件
- **处理**: 完全本地，无数据上传
