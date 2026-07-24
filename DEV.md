# Image Composite Skill - Development Doc

## Purpose
Multi-temporal image compositing from local GeoTIFF files with cloud masking.

## Libraries
- `rasterio` for reading/writing GeoTIFF
- `numpy` for array operations

## CLI Design
```
image-composite composite --inputs scene1.tif scene2.tif scene3.tif --output composite.tif
image-composite composite --inputs *.tif --method median --output composite.tif
image-composite cloud-mask --input scene.tif --qa-band QA_PIXEL --output masked.tif
```

### Subcommands
- `composite`: create composite
  - `--inputs`: input GeoTIFF files (2+)
  - `--output`: output composite path
  - `--method`: compositing method (median, mean, maxNDVI, minRed)
  - `--cloud-mask`: optional cloud mask file
- `cloud-mask`: apply cloud mask
  - `--input`: input file
  - `--qa-band`: QA band name or index
  - `--threshold`: threshold for cloud detection
  - `--output`: output path

## Privacy
- All processing is local. No data sent anywhere.

## Error Handling
- Handle missing rasterio gracefully
- Validate input files exist
- Handle different extents/resolutions
