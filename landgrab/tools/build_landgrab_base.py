"""Build reusable 0.1-degree global land-cover and surface-elevation grids."""

import argparse
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_bounds

from build_landgrab_maps import LAND_COVER_URL, OUTPUT

WIDTH = 3600
HEIGHT = 1800
LAND_COVER_TOP_ROW = 100
LAND_COVER_BOTTOM_ROW = 1500


def write_grid(path, data, description, nodata=None):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=WIDTH,
        height=HEIGHT,
        count=1,
        dtype=data.dtype,
        crs="EPSG:4326",
        transform=from_bounds(-180, -90, 180, 90, WIDTH, HEIGHT),
        compress="deflate",
        tiled=True,
        nodata=nodata,
    ) as output:
        output.write(data, 1)
        output.set_band_description(1, description)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("elevation", help="Path to ETOPO 2022 60-second surface GeoTIFF")
    parser.add_argument(
        "--land-cover",
        default=LAND_COVER_URL,
        help="Copernicus LC100 GeoTIFF path or URL",
    )
    args = parser.parse_args()

    OUTPUT.mkdir(parents=True, exist_ok=True)
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open(args.land_cover) as source:
            if (
                source.crs != rasterio.crs.CRS.from_epsg(4326)
                or not np.allclose(source.bounds, (-180, -60, 180, 80))
            ):
                raise ValueError("Unexpected land-cover source CRS or bounds")
            cover = np.full((HEIGHT, WIDTH), 255, dtype=np.uint8)
            cover[LAND_COVER_TOP_ROW:LAND_COVER_BOTTOM_ROW] = source.read(
                1,
                out_shape=(LAND_COVER_BOTTOM_ROW - LAND_COVER_TOP_ROW, WIDTH),
                resampling=Resampling.nearest,
            )
        with rasterio.open(args.elevation) as source:
            if (
                source.crs is None
                or source.crs.to_epsg() not in (4326, 9518)
                or not np.allclose(source.bounds, (-180, -90, 180, 90), atol=0.1)
            ):
                raise ValueError("Unexpected elevation source CRS or bounds")
            elevation = source.read(
                1, out_shape=(HEIGHT, WIDTH), resampling=Resampling.nearest
            )
            if not np.isfinite(elevation).all() or (
                source.nodata is not None and np.any(elevation == source.nodata)
            ):
                raise ValueError("Elevation source contains missing values")
            if np.any((elevation < -32768) | (elevation > 32767)):
                raise ValueError("Elevation exceeds the 16-bit signed range")
            elevation = np.rint(elevation).astype(np.int16)

    water = np.isin(cover, (80, 200))
    water |= np.isin(cover, (0, 255)) & (elevation <= 0)
    elevation[water] = 0
    write_grid(OUTPUT / "global_landcover.tif", cover, "Copernicus LC100 class", 255)
    write_grid(OUTPUT / "global_elevation.tif", elevation, "Surface elevation (metres)")
    print(f"Saved global 0.1-degree grids ({WIDTH} x {HEIGHT}).")


if __name__ == "__main__":
    main()
