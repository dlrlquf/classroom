"""Prepare country maps from Natural Earth and the saved global terrain grids."""

import json
import math
from pathlib import Path

import numpy as np
import rasterio
import shapefile
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import from_bounds
from rasterio.windows import from_bounds as window_from_bounds

from build_landgrab_maps import OUTPUT

MAX_DIMENSION = 300
COUNTRIES = OUTPUT / "ne_10m_admin_0_countries" / "ne_10m_admin_0_countries.shp"
PHYSICAL = OUTPUT / "10m_physical"
MAP_DIRECTORY = OUTPUT / "country_maps"


def polygon_area(polygon):
    ring = polygon[0]
    area = abs(sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1])
    )) / 2
    latitude = sum(point[1] for point in ring) / len(ring)
    return area * math.cos(math.radians(latitude))


def mainland_bounds(geometry):
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    mainland = max(polygons, key=polygon_area)
    ring = mainland[0]
    left = min(point[0] for point in ring)
    right = max(point[0] for point in ring)
    bottom = min(point[1] for point in ring)
    top = max(point[1] for point in ring)
    pad_x = (right - left) * 0.05
    pad_y = (top - bottom) * 0.05
    return (
        max(-180, left - pad_x), max(-90, bottom - pad_y),
        min(180, right + pad_x), min(90, top + pad_y),
    )


def dimensions(bounds, width=MAX_DIMENSION):
    left, bottom, right, top = bounds
    longitude_scale = max(math.cos(math.radians((bottom + top) / 2)), 0.01)
    aspect = (top - bottom) / ((right - left) * longitude_scale) * math.sqrt(3) / 1.5
    width = max(3, min(width, math.floor(MAX_DIMENSION / aspect)))
    return width, max(3, min(MAX_DIMENSION, round(width * aspect)))


def load_shapes(path):
    with shapefile.Reader(str(path), encoding="utf-8", encodingErrors="strict") as reader:
        return [(shape.bbox, shape.__geo_interface__) for shape in reader.iterShapes()]


def mask_for_bounds(shapes, bounds, width, height):
    left, bottom, right, top = bounds
    matching = [
        (geometry, 1)
        for (x1, y1, x2, y2), geometry in shapes
        if x1 <= right and x2 >= left and y1 <= top and y2 >= bottom
    ]
    if not matching:
        return np.zeros((height, width), dtype=np.uint8)
    return rasterize(
        matching, out_shape=(height, width), transform=from_bounds(*bounds, width, height),
        fill=0, dtype=np.uint8,
    )


def map_rows(bounds, width, height, land_shapes, lake_shapes, deep_shapes, cover, elevation):
    window = window_from_bounds(*bounds, transform=cover.transform)
    covers = cover.read(1, window=window, out_shape=(height, width), resampling=Resampling.nearest)
    elevations = elevation.read(
        1, window=window, out_shape=(height, width), resampling=Resampling.nearest,
    )
    valid_cover = {0, 20, 30, 40, 50, 60, 70, 80, 90, 100, 200, 255}
    valid_cover.update(range(111, 117))
    valid_cover.update(range(121, 127))
    unknown_cover = set(np.unique(covers)) - valid_cover
    if unknown_cover:
        raise ValueError(f"Unknown land-cover classes: {sorted(unknown_cover)}")
    land = mask_for_bounds(land_shapes, bounds, width, height)
    lakes = mask_for_bounds(lake_shapes, bounds, width, height)
    deep = mask_for_bounds(deep_shapes, bounds, width, height)
    terrain = np.full((height, width), ord("g"), dtype=np.uint8)
    terrain[covers == 40] = ord("p")
    terrain[covers == 90] = ord("t")
    terrain[covers == 20] = ord("b")
    forest = ((covers >= 111) & (covers <= 116)) | ((covers >= 121) & (covers <= 126))
    terrain[forest] = ord("f")
    latitudes = bounds[3] - (np.arange(height) + 0.5) * (bounds[3] - bounds[1]) / height
    terrain[forest & (np.abs(latitudes[:, None]) <= 23.5)] = ord("j")
    terrain[covers == 60] = ord("d")
    hills = (elevations >= 250) & (elevations < 700) & np.isin(terrain, (ord("g"), ord("p"), ord("b")))
    terrain[hills] = ord("h")
    terrain[elevations >= 700] = ord("m")
    terrain[(elevations >= 700) & (covers == 60)] = ord("k")
    relief = np.zeros_like(elevations, dtype=np.int32)
    vertical = np.abs(np.diff(elevations.astype(np.int32), axis=0))
    horizontal = np.abs(np.diff(elevations.astype(np.int32), axis=1))
    relief[:-1, :] = np.maximum(relief[:-1, :], vertical)
    relief[1:, :] = np.maximum(relief[1:, :], vertical)
    relief[:, :-1] = np.maximum(relief[:, :-1], horizontal)
    relief[:, 1:] = np.maximum(relief[:, 1:], horizontal)
    terrain[(elevations >= 700) & (relief >= 400)] = ord("v")
    terrain[covers == 70] = ord("n")
    terrain[land == 0] = ord("c")
    terrain[(land == 0) & (deep != 0)] = ord("w")
    terrain[lakes != 0] = ord("l")
    return ["".join(chr(value) for value in row) for row in terrain]


def main():
    MAP_DIRECTORY.mkdir(parents=True, exist_ok=True)
    land_shapes = load_shapes(PHYSICAL / "ne_10m_land.shp")
    lake_shapes = load_shapes(PHYSICAL / "ne_10m_lakes.shp")
    deep_shapes = load_shapes(PHYSICAL / "ne_10m_bathymetry_K_200.shp")
    countries = []
    with (
        shapefile.Reader(str(COUNTRIES), encoding="utf-8", encodingErrors="strict") as reader,
        rasterio.open(OUTPUT / "global_landcover.tif") as cover,
        rasterio.open(OUTPUT / "global_elevation.tif") as elevation,
    ):
        if (
            cover.crs != rasterio.crs.CRS.from_epsg(4326)
            or cover.crs != elevation.crs
            or cover.transform != elevation.transform
            or cover.shape != elevation.shape
            or cover.bounds != rasterio.coords.BoundingBox(-180, -90, 180, 90)
        ):
            raise ValueError("Saved global grids have incompatible georeferencing")
        for item in reader.iterShapeRecords():
            record = item.record.as_dict()
            country_id = str(record["NE_ID"])
            name = record["NAME_KO"] or record["NAME_EN"]
            bounds = mainland_bounds(item.shape.__geo_interface__)
            width, height = dimensions(bounds)
            rows = map_rows(
                bounds, width, height, land_shapes, lake_shapes, deep_shapes, cover, elevation,
            )
            (MAP_DIRECTORY / (country_id + ".txt")).write_text(
                "\n".join(rows) + "\n", encoding="ascii",
            )
            countries.append({"id": country_id, "name": name, "width": width, "height": height})
        for name, bounds, width, height in (
            ("world", (-180, -90, 180, 90), 100, 70),
            ("korea", (124, 32.5, 132, 43.5), 160, 220),
        ):
            rows = map_rows(
                bounds, width, height, land_shapes, lake_shapes, deep_shapes, cover, elevation,
            )
            (OUTPUT / (name + ".txt")).write_text("\n".join(rows) + "\n", encoding="ascii")
    countries.sort(key=lambda country: country["name"])
    (OUTPUT / "countries.json").write_text(
        json.dumps(countries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(f"Prepared {len(countries)} country maps.")


if __name__ == "__main__":
    main()
