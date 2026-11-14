
"""
VYOMARA — Earth Elevation Grid Builder
Extracts real 10 km elevation grids from the existing Copernicus cache.

No network requests.
No synthetic elevation data.
"""

from pathlib import Path
import json
import math

import numpy as np
import rasterio

from rasterio.merge import merge


ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "cache" / "earth"
OUTPUT = ROOT / "data" / "earth_grids"

EARTH_RADIUS = 6371000.0
RADIUS_KM = 10.0

CANDIDATES = [
    ("McMurdo Dry Valleys", "Antarctica", -77.5, 162.5),
    ("Qaidam Basin", "China", 37.5, 95.0),
    ("Atacama Desert", "Chile", -24.5, -69.25),
    ("Sahara Desert", "North Africa", 23.5, 13.0),
    ("Icelandic Highlands", "Iceland", 64.5, -18.5),
    ("Tibetan Plateau", "China", 32.0, 88.0),
    ("Andes Mountains", "Argentina", -32.0, -70.0),
    ("Namib Desert", "Namibia", -24.0, 15.0),
    ("Western Australian Outback", "Australia", -25.0, 122.0),
    ("Colorado Plateau", "United States", 36.5, -111.5),
    ("Patagonian Plateau", "Argentina", -49.0, -70.0),
    ("Arabian Desert", "Saudi Arabia", 22.0, 45.0),
    ("Gobi Desert", "Mongolia", 43.0, 103.0),
    ("Ethiopian Highlands", "Ethiopia", 9.0, 39.0),
    ("Canadian Arctic", "Canada", 74.0, -90.0),
    ("New Zealand Southern Alps", "New Zealand", -43.5, 170.0),
    ("Death Valley", "United States", 36.2, -116.8),
    ("Himalayan Region", "Nepal", 28.0, 86.0),
]


def identifier(name):
    return "earth-" + name.lower().replace(" ", "-")


def bounds_for(lat, lon):
    angular = (RADIUS_KM * 1000.0) / EARTH_RADIUS
    lat_delta = math.degrees(angular)

    cosine = abs(math.cos(math.radians(lat)))

    if cosine < 1e-6:
        lon_delta = 180.0
    else:
        lon_delta = min(lat_delta / cosine, 180.0)

    return (
        lon - lon_delta,
        max(-90.0, lat - lat_delta),
        lon + lon_delta,
        min(90.0, lat + lat_delta),
    )


def intersects(a, b):
    return (
        a.left < b[2]
        and a.right > b[0]
        and a.bottom < b[3]
        and a.top > b[1]
    )


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)

    if not CACHE.exists():
        raise RuntimeError(f"Earth cache not found: {CACHE}")

    tile_files = sorted(CACHE.glob("*.tif"))

    if not tile_files:
        raise RuntimeError("No cached Earth TIFF tiles found.")

    print(f"Found {len(tile_files)} cached TIFF files.")
    print(f"Building {len(CANDIDATES)} grids at {RADIUS_KM} km.")
    print("Network access is not used.")

    successful = []
    failures = []

    for index, (name, country, lat, lon) in enumerate(
        CANDIDATES, start=1
    ):
        print(f"\n[{index}/{len(CANDIDATES)}] {name}")

        bounds = bounds_for(lat, lon)
        datasets = []

        try:
            for path in tile_files:
                src = rasterio.open(path)

                if src.crs is None or not src.crs.is_geographic:
                    src.close()
                    continue

                if intersects(src.bounds, bounds):
                    datasets.append(src)
                else:
                    src.close()

            if not datasets:
                raise RuntimeError(
                    "No cached tiles intersect this candidate."
                )

            print(
                "  Source tiles:",
                ", ".join(
                    Path(src.name).name for src in datasets
                )
            )

            merged, transform = merge(
                datasets,
                bounds=bounds,
                nodata=np.nan,
                dtype="float32",
            )

            elevation = np.asarray(
                merged[0],
                dtype=np.float32,
            )

            elevation[~np.isfinite(elevation)] = np.nan

            valid = np.isfinite(elevation)
            valid_count = int(np.count_nonzero(valid))
            valid_fraction = valid_count / elevation.size

            if elevation.shape[0] < 5 or elevation.shape[1] < 5:
                raise RuntimeError("Grid is too small.")

            if valid_fraction < 0.50:
                raise RuntimeError(
                    f"Insufficient valid coverage: "
                    f"{valid_fraction:.2%}"
                )

            grid_id = identifier(name)
            output_file = OUTPUT / f"{grid_id}.npz"

            metadata = {
                "id": grid_id,
                "name": name,
                "country": country,
                "latitude": lat,
                "longitude": lon,
                "radius_km": RADIUS_KM,
                "source": "Copernicus DEM GLO-90",
                "source_product_type": "Digital Surface Model",
                "source_tiles": [
                    Path(src.name).name for src in datasets
                ],
                "crs": "EPSG:4326",
                "transform": list(transform)[:6],
                "shape": list(elevation.shape),
                "valid_fraction": valid_fraction,
                "valid_pixel_count": valid_count,
                "elevation_units": "metres",
            }

            np.savez_compressed(
                output_file,
                elevation=elevation,
                metadata=np.array(json.dumps(metadata)),
            )

            size_mb = output_file.stat().st_size / (1024 * 1024)

            print(
                f"  Grid: {elevation.shape[1]} x "
                f"{elevation.shape[0]} pixels"
            )
            print(f"  Valid coverage: {valid_fraction:.2%}")
            print(f"  Saved: {output_file.name} ({size_mb:.2f} MB)")

            successful.append(grid_id)

        except Exception as exc:
            print(f"  FAILED: {exc}")
            failures.append({
                "candidate": name,
                "reason": str(exc),
            })

        finally:
            for src in datasets:
                src.close()

    manifest = {
        "dataset": "Copernicus DEM GLO-90",
        "dataset_type": "Digital Surface Model",
        "radius_km": RADIUS_KM,
        "candidate_count": len(CANDIDATES),
        "successful_count": len(successful),
        "failed_count": len(failures),
        "successful_grids": successful,
        "failures": failures,
    }

    with open(OUTPUT / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print("\n" + "=" * 55)
    print("GRID GENERATION COMPLETE")
    print("=" * 55)
    print(f"Successful: {len(successful)}/{len(CANDIDATES)}")
    print(f"Failed: {len(failures)}")
    print(f"Output directory: {OUTPUT}")

    if failures:
        print("\nFailed candidates:")
        for item in failures:
            print(f"  - {item['candidate']}: {item['reason']}")

        raise SystemExit(
            "Not all grids were generated. Do not deploy yet."
        )


if __name__ == "__main__":
    main()