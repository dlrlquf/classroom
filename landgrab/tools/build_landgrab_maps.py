"""Build the bundled landgrab maps from Copernicus LC100 and NOAA ETOPO 2022."""

import argparse
from pathlib import Path

LAND_COVER_URL = "https://s3-west.nrp-nautilus.io/public-land-cover/cgls-lc100-2019-cog.tif"
OUTPUT = Path(__file__).resolve().parent.parent / "data"
MAPS = {
    "world": ((-180, -90, 180, 90), 400, 280),
    "korea": ((124, 32.5, 132, 43.5), 160, 220),
}
WORLD_WIDTH = 100
WORLD_HEIGHT = 70


def read_elevation(source, bounds, width, height):
    from rasterio.enums import Resampling
    from rasterio.windows import from_bounds

    return source.read(
        1,
        window=from_bounds(*bounds, transform=source.transform),
        out_shape=(height, width),
        resampling=Resampling.nearest,
    )


def land_cover_for_map(source, bounds, width, height, overview):
    import numpy as np
    from rasterio.enums import Resampling
    from rasterio.windows import from_bounds

    left, bottom, right, top = bounds
    result = np.full((height, width), 255, dtype=np.uint8)
    if overview is not None:
        for row in range(height):
            lat = top - (row + 0.5) * (top - bottom) / height
            if -60 <= lat < 80:
                source_row = min(int((80 - lat) / 140 * overview.shape[0]), overview.shape[0] - 1)
                result[row] = overview[source_row]
    else:
        result = source.read(
            1,
            window=from_bounds(left, bottom, right, top, transform=source.transform),
            out_shape=(height, width),
            resampling=Resampling.nearest,
        )
    return result


def terrain(cover, elevation):
    if cover in (80, 200):
        return "w"
    if cover in (0, 255):
        return "w" if elevation <= 0 else ("m" if elevation >= 700 else "g")
    if cover not in (20, 30, 40, 50, 60, 70, 90, 100, *range(111, 117), *range(121, 127)):
        raise ValueError(f"Unknown land-cover class: {cover}")
    if elevation >= 700:
        return "m"
    if 111 <= cover <= 126:
        return "f"
    if cover == 60:
        return "d"
    return "g"


def terrain_rows(covers, elevations):
    return [
        "".join(terrain(int(c), int(e)) for c, e in zip(cover_row, elevation_row))
        for cover_row, elevation_row in zip(covers, elevations)
    ]


def world_terrain(covers, elevations):
    water = 0
    land_elevation = 0
    land_count = 0
    land_types = {"g": 0, "f": 0, "d": 0}
    for cover_row, elevation_row in zip(covers, elevations):
        for cover, elevation in zip(cover_row, elevation_row):
            cover, elevation = int(cover), int(elevation)
            if terrain(cover, elevation) == "w":
                water += 1
            else:
                land_count += 1
                land_elevation += elevation
                land_type = "g" if cover in (0, 255) else terrain(cover, 0)
                land_types[land_type] += 1
    if water + land_count == 0:
        raise ValueError("Cannot classify an empty world-map region")
    if water * 10 >= (water + land_count) * 9:
        return "w"
    if land_elevation >= 1000 * land_count:
        return "m"
    return max(land_types, key=land_types.get)


def world_terrain_rows(covers, elevations, width, height):
    source_height, source_width = covers.shape
    if (
        elevations.shape != covers.shape
        or not 1 <= width <= source_width
        or not 1 <= height <= source_height
    ):
        raise ValueError("Invalid global grids or world map dimensions")
    return [
        "".join(
            world_terrain(
                covers[row * source_height // height:(row + 1) * source_height // height,
                       column * source_width // width:(column + 1) * source_width // width],
                elevations[row * source_height // height:(row + 1) * source_height // height,
                           column * source_width // width:(column + 1) * source_width // width],
            )
            for column in range(width)
        )
        for row in range(height)
    ]


def main():
    import rasterio

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "elevation", nargs="?", help="Path to ETOPO 2022 60-second surface GeoTIFF"
    )
    parser.add_argument(
        "--world-from-base", action="store_true",
        help="Regenerate only the world map from the saved global grids",
    )
    args = parser.parse_args()
    if args.world_from_base and args.elevation:
        parser.error("--world-from-base does not accept an elevation source")
    if not args.world_from_base and not args.elevation:
        parser.error("an elevation source is required unless --world-from-base is used")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    if args.world_from_base:
        width, height = WORLD_WIDTH, WORLD_HEIGHT
        with (
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
            covers = cover.read(1)
            elevations = elevation.read(1)
        rows = world_terrain_rows(covers, elevations, width, height)
        (OUTPUT / "world.txt").write_text("\n".join(rows) + "\n", encoding="ascii")
        print(f"world: {width} x {height}")
        return

    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        from rasterio.enums import Resampling

        with rasterio.open(LAND_COVER_URL) as cover, rasterio.open(args.elevation) as elevation:
            overview = cover.read(
                1, out_shape=(280, 400), resampling=Resampling.nearest
            )
            for name, (bounds, width, height) in MAPS.items():
                elevations = read_elevation(elevation, bounds, width, height)
                covers = land_cover_for_map(
                    cover, bounds, width, height, overview if name == "world" else None
                )
                rows = terrain_rows(covers, elevations)
                (OUTPUT / f"{name}.txt").write_text("\n".join(rows) + "\n", encoding="ascii")
                print(f"{name}: {width} x {height}")


if __name__ == "__main__":
    main()
