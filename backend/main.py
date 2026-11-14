
"""
VYOMARA — Scientific Backend
Version: 4.3.0

Run from project root:
python -m uvicorn main:app --app-dir backend --reload --host 127.0.0.1 --port 8000

Dependencies:
pip install fastapi uvicorn numpy rasterio requests

Data:
    data/moon_lola_dem.tif
    data/mars_mola_dem.tif
    data/earth_grids/*.npz
    data/earth_grids/manifest.json

Earth:
    18 pre-extracted Copernicus DEM GLO-90 elevation grids.
    No runtime Copernicus tile retrieval.

Scientific integrity:
- Real DEM-derived terrain measurements only.
- NASA LOLA/MOLA provenance for recognized configured filenames.
- Copernicus DEM GLO-90 provenance for stored Earth grids.
- 18 predefined Earth screening locations, NOT global discovery.
- Similarity scores are exploratory comparative indices.
- Scores are not probabilities or validated scientific confidence.
- DEM resolutions differ; slope and roughness are resolution-dependent.
- Absolute elevations are not included in the similarity score.
"""

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from affine import Affine
from rasterio.windows import from_bounds, Window
from rasterio.transform import array_bounds
from rasterio.errors import WindowError
from rasterio.warp import transform_bounds

import os
import math
import json
import logging
import time
import threading
import requests
import numpy as np
import rasterio


# ============================================================
# CONFIGURATION
# ============================================================

APP_NAME = "VYOMARA Scientific Engine"
VERSION = "4.3.0"

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"

EARTH_GRID_DIR = DATA_DIR / "earth_grids"
EARTH_MANIFEST_PATH = EARTH_GRID_DIR / "manifest.json"

CACHE_DIR.mkdir(parents=True, exist_ok=True)

MOON_DEM_PATH = Path(
    os.getenv(
        "MOON_DEM_PATH",
        str(DATA_DIR / "moon_lola_dem.tif")
    )
)

MARS_DEM_PATH = Path(
    os.getenv(
        "MARS_DEM_PATH",
        str(DATA_DIR / "mars_mola_dem.tif")
    )
)

MOON_DEM_URL = os.getenv("MOON_DEM_URL", "").strip()
MARS_DEM_URL = os.getenv("MARS_DEM_URL", "").strip()

REQUEST_TIMEOUT = 90
MAX_DOWNLOAD_SIZE = 512 * 1024 * 1024
DOWNLOAD_RETRIES = 3

MAX_RADIUS_KM = 100.0

# Earth grids were extracted at this radius.
EARTH_GRID_RADIUS_KM = 10.0

MIN_VALID_FRACTION = 0.50

PLANET_RADII = {
    "earth": 6371000.0,
    "moon": 1737400.0,
    "mars": 3396000.0,
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VYOMARA")


# ============================================================
# DOWNLOAD CONCURRENCY CONTROL
# Used only for Moon/Mars remote DEM downloads.
# ============================================================

_DOWNLOAD_LOCKS: Dict[str, threading.Lock] = {}
_DOWNLOAD_LOCKS_GUARD = threading.Lock()


def get_download_lock(destination: Path) -> threading.Lock:
    key = str(destination.resolve())

    with _DOWNLOAD_LOCKS_GUARD:
        if key not in _DOWNLOAD_LOCKS:
            _DOWNLOAD_LOCKS[key] = threading.Lock()

        return _DOWNLOAD_LOCKS[key]


# ============================================================
# APPLICATION
# ============================================================

app = FastAPI(
    title=APP_NAME,
    description=(
        "Planetary terrain analysis and Earth analogue screening "
        "using real digital elevation models."
    ),
    version=VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://vyomara.space",
        "https://vyomara-frontend.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# DATA PROVENANCE
# ============================================================

PLANETARY_PROVENANCE = {
    "moon": {
        "provider": "NASA",
        "data_archive": "NASA Planetary Data System",
        "archive_node": "PDS Geosciences Node",
        "mission": "Lunar Reconnaissance Orbiter (LRO)",
        "instrument": "Lunar Orbiter Laser Altimeter (LOLA)",
        "dataset_id": "LRO-L-LOLA-3-RDR-V1.0",
        "product_id": "LDEM_64.JP2",
        "source_product": (
            "https://pds-geosciences.wustl.edu/"
            "lro/lro-l-lola-3-rdr-v1/"
            "lrolol_1xxx/data/lola_gdr/cylindrical/jp2/"
        ),
        "elevation_units": "metres",
        "vertical_reference": "GCS_Moon_2000",
        "model_type": "Lunar digital elevation model",
        "nominal_resolution": "64 pixels per degree",
    },

    "mars": {
        "provider": "NASA",
        "data_archive": "NASA Planetary Data System",
        "archive_node": "PDS Geosciences Node",
        "mission": "Mars Global Surveyor (MGS)",
        "instrument": "Mars Orbiter Laser Altimeter (MOLA)",
        "dataset_id": "MGS-M-MOLA-5-MEGDR-L3-V1.0",
        "product_id": "MEGT90N000FB.IMG",
        "source_product": (
            "https://pds-geosciences.wustl.edu/"
            "mgs/mgs-m-mola-5-megdr-l3-v1/"
            "mgsl_300x/meg032/"
        ),
        "elevation_units": "metres",
        "vertical_reference": "MOLA areoid GMM3 degree/order 50",
        "model_type": "Martian digital elevation model",
        "nominal_resolution": "32 pixels per degree",
    },
}

EARTH_PROVENANCE = {
    "provider": "Copernicus Programme",
    "dataset": "Copernicus DEM GLO-90",
    "product_type": "Digital Surface Model",
    "nominal_resolution": "90 metres",
    "source_url": "https://dataspace.copernicus.eu/",
    "model_type": "Digital Surface Model",
    "storage_method": "Pre-extracted compressed NumPy elevation grids",
    "runtime_tile_retrieval": False,
}


def get_planetary_provenance(
    planet: str,
    dem_path: Path,
) -> Dict[str, Any]:

    expected_names = {
        "moon": "moon_lola_dem.tif",
        "mars": "mars_mola_dem.tif",
    }

    if dem_path.name.lower() != expected_names[planet]:
        return {
            "provider": "User-configured",
            "provenance_status": "Not independently verified",
            "source_file": str(dem_path),
            "model_type": "User-configured planetary DEM",
        }

    provenance = PLANETARY_PROVENANCE[planet].copy()

    provenance["provenance_status"] = (
        "Configured filename matches the expected NASA-derived DEM; "
        "file contents have not been independently authenticated."
    )

    return provenance


# ============================================================
# EARTH SCREENING LOCATIONS
# ============================================================

EARTH_SCREENING_POINTS = [
    {
        "name": "McMurdo Dry Valleys",
        "country": "Antarctica",
        "lat": -77.5,
        "lon": 162.5,
    },
    {
        "name": "Qaidam Basin",
        "country": "China",
        "lat": 37.5,
        "lon": 95.0,
    },
    {
        "name": "Atacama Desert",
        "country": "Chile",
        "lat": -24.5,
        "lon": -69.25,
    },
    {
        "name": "Sahara Desert",
        "country": "North Africa",
        "lat": 23.5,
        "lon": 13.0,
    },
    {
        "name": "Icelandic Highlands",
        "country": "Iceland",
        "lat": 64.5,
        "lon": -18.5,
    },
    {
        "name": "Tibetan Plateau",
        "country": "China",
        "lat": 32.0,
        "lon": 88.0,
    },
    {
        "name": "Andes Mountains",
        "country": "Argentina",
        "lat": -32.0,
        "lon": -70.0,
    },
    {
        "name": "Namib Desert",
        "country": "Namibia",
        "lat": -24.0,
        "lon": 15.0,
    },
    {
        "name": "Western Australian Outback",
        "country": "Australia",
        "lat": -25.0,
        "lon": 122.0,
    },
    {
        "name": "Colorado Plateau",
        "country": "United States",
        "lat": 36.5,
        "lon": -111.5,
    },
    {
        "name": "Patagonian Plateau",
        "country": "Argentina",
        "lat": -49.0,
        "lon": -70.0,
    },
    {
        "name": "Arabian Desert",
        "country": "Saudi Arabia",
        "lat": 22.0,
        "lon": 45.0,
    },
    {
        "name": "Gobi Desert",
        "country": "Mongolia",
        "lat": 43.0,
        "lon": 103.0,
    },
    {
        "name": "Ethiopian Highlands",
        "country": "Ethiopia",
        "lat": 9.0,
        "lon": 39.0,
    },
    {
        "name": "Canadian Arctic",
        "country": "Canada",
        "lat": 74.0,
        "lon": -90.0,
    },
    {
        "name": "New Zealand Southern Alps",
        "country": "New Zealand",
        "lat": -43.5,
        "lon": 170.0,
    },
    {
        "name": "Death Valley",
        "country": "United States",
        "lat": 36.2,
        "lon": -116.8,
    },
    {
        "name": "Himalayan Region",
        "country": "Nepal",
        "lat": 28.0,
        "lon": 86.0,
    },
]


def candidate_identifier(candidate: Dict[str, Any]) -> str:
    slug = (
        candidate["name"]
        .lower()
        .replace(" ", "-")
    )

    return "earth-" + slug


def candidate_grid_path(candidate: Dict[str, Any]) -> Path:
    return (
        EARTH_GRID_DIR
        / f"{candidate_identifier(candidate)}.npz"
    )


# ============================================================
# VALIDATION
# ============================================================

def validate_planet(planet: str) -> str:
    planet = planet.lower().strip()

    if planet not in ("moon", "mars"):
        raise HTTPException(
            status_code=400,
            detail="Planet must be either 'moon' or 'mars'.",
        )

    return planet


def validate_coordinates(lat: float, lon: float):
    if not math.isfinite(lat) or not math.isfinite(lon):
        raise HTTPException(
            status_code=400,
            detail="Coordinates must be finite numbers.",
        )

    if not -90 <= lat <= 90:
        raise HTTPException(
            status_code=400,
            detail="Latitude must be between -90 and 90.",
        )

    if not -180 <= lon <= 180:
        raise HTTPException(
            status_code=400,
            detail="Longitude must be between -180 and 180.",
        )


def validate_radius(radius_km: float):
    if not math.isfinite(radius_km):
        raise HTTPException(
            status_code=400,
            detail="Radius must be finite.",
        )

    if not 0 < radius_km <= MAX_RADIUS_KM:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Radius must be greater than 0 "
                f"and at most {MAX_RADIUS_KM:g} km."
            ),
        )


# ============================================================
# RASTER VALIDATION
# ============================================================

def raster_is_usable(path: Path) -> bool:
    if not path.exists():
        return False

    try:
        if path.stat().st_size == 0:
            return False

        with rasterio.open(path) as dataset:
            return (
                dataset.count >= 1
                and dataset.crs is not None
                and dataset.width > 0
                and dataset.height > 0
            )

    except Exception:
        return False


def validate_raster(path: Path):
    if not raster_is_usable(path):
        raise ValueError(
            f"Raster is missing or unusable: {path}"
        )

    with rasterio.open(path) as dataset:
        if dataset.count < 1:
            raise ValueError("Raster contains no bands.")

        if dataset.width < 5 or dataset.height < 5:
            raise ValueError("Raster dimensions are too small.")

        if not all(
            math.isfinite(value)
            for value in dataset.bounds
        ):
            raise ValueError("Raster bounds are invalid.")


# ============================================================
# PLANETARY DEM DOWNLOAD ENGINE
# ============================================================

def _download_file_unlocked(
    url: str,
    destination: Path,
) -> Path:

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if destination.exists() and raster_is_usable(destination):
        return destination

    if destination.exists():
        destination.unlink(missing_ok=True)

    temporary = destination.with_suffix(
        destination.suffix + ".partial"
    )

    last_error = None

    for attempt in range(DOWNLOAD_RETRIES):
        try:
            temporary.unlink(missing_ok=True)

            logger.info(
                "Planetary DEM download attempt %s/%s: %s",
                attempt + 1,
                DOWNLOAD_RETRIES,
                url,
            )

            total = 0

            with requests.get(
                url,
                stream=True,
                timeout=(15, REQUEST_TIMEOUT),
                headers={
                    "User-Agent": (
                        "VYOMARA-Scientific-Engine/4.3.0"
                    )
                },
            ) as response:

                response.raise_for_status()

                content_length = response.headers.get(
                    "Content-Length"
                )

                if content_length:
                    try:
                        expected_size = int(content_length)
                    except ValueError:
                        raise ValueError(
                            "Remote server returned invalid Content-Length."
                        )

                    if expected_size > MAX_DOWNLOAD_SIZE:
                        raise ValueError(
                            "Remote file exceeds configured download limit."
                        )

                content_type = response.headers.get(
                    "Content-Type",
                    "",
                ).lower()

                if (
                    "text/html" in content_type
                    or "application/xml" in content_type
                ):
                    raise ValueError(
                        "Remote server returned HTML/XML instead of a raster."
                    )

                with open(temporary, "wb") as file:
                    for chunk in response.iter_content(
                        chunk_size=1024 * 1024
                    ):
                        if not chunk:
                            continue

                        total += len(chunk)

                        if total > MAX_DOWNLOAD_SIZE:
                            raise ValueError(
                                "Download exceeded configured size limit."
                            )

                        file.write(chunk)

            if total == 0:
                raise ValueError("Downloaded file is empty.")

            with open(temporary, "rb") as file:
                signature = file.read(4)

            valid_tiff_signatures = (
                b"II*\x00",
                b"MM\x00*",
                b"II+\x00",
                b"MM\x00+",
            )

            if signature not in valid_tiff_signatures:
                raise ValueError(
                    "Downloaded response is not a recognized TIFF file."
                )

            with rasterio.open(temporary) as dataset:
                if dataset.count < 1:
                    raise ValueError(
                        "Downloaded raster contains no bands."
                    )

                if dataset.crs is None:
                    raise ValueError(
                        "Downloaded raster has no CRS."
                    )

                if dataset.width < 5 or dataset.height < 5:
                    raise ValueError(
                        "Downloaded raster dimensions are invalid."
                    )

                if not all(
                    math.isfinite(value)
                    for value in dataset.bounds
                ):
                    raise ValueError(
                        "Downloaded raster bounds are invalid."
                    )

            temporary.replace(destination)

            logger.info(
                "Planetary DEM download completed: %s (%s bytes)",
                destination.name,
                total,
            )

            return destination

        except Exception as exc:
            last_error = exc

            logger.warning(
                "Download attempt %s failed: %s",
                attempt + 1,
                exc,
            )

            temporary.unlink(missing_ok=True)

            if attempt + 1 < DOWNLOAD_RETRIES:
                time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(
        f"Download failed after {DOWNLOAD_RETRIES} attempts: {last_error}"
    )


def download_file(
    url: str,
    destination: Path,
) -> Path:

    lock = get_download_lock(destination)

    with lock:
        return _download_file_unlocked(
            url,
            destination,
        )


def get_planet_dem_path(planet: str) -> Path:
    if planet == "moon":
        local_path = MOON_DEM_PATH
        remote_url = MOON_DEM_URL
    else:
        local_path = MARS_DEM_PATH
        remote_url = MARS_DEM_URL

    if local_path.exists():
        try:
            validate_raster(local_path)
            return local_path
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"{planet.upper()} DEM is unusable: {exc}",
            )

    if remote_url:
        destination = CACHE_DIR / f"{planet}_remote_dem.tif"

        try:
            return download_file(
                remote_url,
                destination,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Could not retrieve {planet.upper()} DEM: {exc}",
            )

    raise HTTPException(
        status_code=503,
        detail=(
            f"{planet.upper()} DEM is not configured. "
            f"Expected: {local_path}"
        ),
    )


# ============================================================
# GEOGRAPHIC GEOMETRY
# ============================================================

def make_geographic_bounds(
    lat: float,
    lon: float,
    radius_km: float,
    planet: str,
) -> Tuple[float, float, float, float]:

    validate_coordinates(lat, lon)
    validate_radius(radius_km)

    radius_m = radius_km * 1000.0
    body_radius = PLANET_RADII[planet]

    latitude_delta = math.degrees(
        radius_m / body_radius
    )

    south = max(-90.0, lat - latitude_delta)
    north = min(90.0, lat + latitude_delta)

    cosine = abs(
        math.cos(math.radians(lat))
    )

    if cosine < 1e-6:
        longitude_delta = 180.0
    else:
        longitude_delta = min(
            latitude_delta / cosine,
            180.0,
        )

    west = lon - longitude_delta
    east = lon + longitude_delta

    return west, south, east, north


# ============================================================
# STORED EARTH GRID LOADER
# ============================================================

def read_grid_metadata(npz_file) -> Dict[str, Any]:
    """
    Read metadata saved by prepare_earth_grids.py.

    Expected NPZ members:
        elevation
        metadata

    Metadata is stored as a JSON string.
    """

    if "metadata" not in npz_file.files:
        raise ValueError(
            "Earth grid is missing its metadata member."
        )

    raw = npz_file["metadata"].item()

    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")

    if isinstance(raw, str):
        metadata = json.loads(raw)
    elif isinstance(raw, dict):
        metadata = raw
    else:
        raise ValueError(
            "Earth grid metadata has an unsupported format."
        )

    if not isinstance(metadata, dict):
        raise ValueError(
            "Earth grid metadata is not a JSON object."
        )

    return metadata


def get_grid_transform(
    metadata: Dict[str, Any],
    elevation: np.ndarray,
) -> Affine:

    transform_values = metadata.get("transform")

    if transform_values is not None:
        if len(transform_values) < 6:
            raise ValueError(
                "Stored grid transform is incomplete."
            )

        return Affine(
            *[float(value) for value in transform_values[:6]]
        )

    # Fallback: reconstruct from stored bounds.
    bounds = metadata.get("bounds")

    if bounds is None:
        raise ValueError(
            "Earth grid has neither transform nor bounds metadata."
        )

    west, south, east, north = [
        float(value) for value in bounds
    ]

    height, width = elevation.shape

    return Affine(
        (east - west) / width,
        0.0,
        west,
        0.0,
        -(north - south) / height,
        north,
    )


def load_earth_grid(
    candidate: Dict[str, Any],
) -> Dict[str, Any]:

    path = candidate_grid_path(candidate)

    if not path.exists():
        raise FileNotFoundError(
            f"Stored Earth grid is missing: {path.name}"
        )

    try:
        with np.load(path, allow_pickle=False) as npz_file:

            if "elevation" not in npz_file.files:
                raise ValueError(
                    "Earth grid has no elevation array."
                )

            # Keep the array float32 to reduce memory use.
            elevation = np.asarray(
                npz_file["elevation"],
                dtype=np.float32,
            )

            metadata = read_grid_metadata(npz_file)

    except Exception as exc:
        raise ValueError(
            f"Could not read {path.name}: {exc}"
        )

    if elevation.ndim != 2:
        raise ValueError(
            "Stored elevation grid must be a 2D array."
        )

    if elevation.shape[0] < 5 or elevation.shape[1] < 5:
        raise ValueError(
            "Stored elevation grid is too small."
        )

    elevation[~np.isfinite(elevation)] = np.nan

    transform = get_grid_transform(
        metadata,
        elevation,
    )

    valid_fraction = float(
        np.count_nonzero(np.isfinite(elevation))
        / elevation.size
    )

    if valid_fraction < MIN_VALID_FRACTION:
        raise ValueError(
            f"Stored grid coverage is too low: {valid_fraction:.1%}"
        )

    return {
        "array": elevation,
        "transform": transform,
        "metadata": metadata,
        "valid_fraction": valid_fraction,
        "source": str(path),
        "planet": "earth",
        "is_geographic": True,
        "center_lat": float(candidate["lat"]),
    }


# ============================================================
# EARTH GRID WINDOW EXTRACTION
# ============================================================

def read_stored_earth_window(
    candidate: Dict[str, Any],
    radius_km: float,
) -> Dict[str, Any]:

    if radius_km > EARTH_GRID_RADIUS_KM + 1e-8:
        raise ValueError(
            "Stored Earth grids cover a maximum radius of "
            f"{EARTH_GRID_RADIUS_KM:g} km. "
            f"Requested radius: {radius_km:g} km."
        )

    grid = load_earth_grid(candidate)

    elevation = grid["array"]
    transform = grid["transform"]

    requested_bounds = make_geographic_bounds(
        candidate["lat"],
        candidate["lon"],
        radius_km,
        "earth",
    )

    west, south, east, north = requested_bounds

    grid_west, grid_south, grid_east, grid_north = (
        array_bounds(
            elevation.shape[0],
            elevation.shape[1],
            transform,
        )
    )

    # Verify that the requested region is contained by the
    # pre-extracted grid. A small tolerance accounts for
    # floating-point transform precision.
    tolerance_x = abs(transform.a) * 1.5
    tolerance_y = abs(transform.e) * 1.5

    if (
        west < grid_west - tolerance_x
        or east > grid_east + tolerance_x
        or south < grid_south - tolerance_y
        or north > grid_north + tolerance_y
    ):
        raise ValueError(
            "Requested region extends beyond the stored Earth grid."
        )

    window = from_bounds(
        west,
        south,
        east,
        north,
        transform=transform,
    )

    col_start = max(
        0,
        math.floor(window.col_off),
    )

    row_start = max(
        0,
        math.floor(window.row_off),
    )

    col_stop = min(
        elevation.shape[1],
        math.ceil(window.col_off + window.width),
    )

    row_stop = min(
        elevation.shape[0],
        math.ceil(window.row_off + window.height),
    )

    if (
        col_stop - col_start < 5
        or row_stop - row_start < 5
    ):
        raise ValueError(
            "Requested Earth region contains too few pixels."
        )

    cropped = elevation[
        row_start:row_stop,
        col_start:col_stop,
    ].copy()

    crop_window = Window(
        col_start,
        row_start,
        col_stop - col_start,
        row_stop - row_start,
    )

    crop_transform = rasterio.windows.transform(
        crop_window,
        transform,
    )

    valid_fraction = float(
        np.count_nonzero(np.isfinite(cropped))
        / cropped.size
    )

    if valid_fraction < MIN_VALID_FRACTION:
        raise ValueError(
            f"Insufficient stored Earth grid coverage: {valid_fraction:.1%}"
        )

    metadata = grid["metadata"]

    original_source_tiles = metadata.get(
        "source_tiles",
        [],
    )

    return {
        "array": cropped,
        "transform": crop_transform,
        "valid_fraction": valid_fraction,
        "crs": "EPSG:4326",
        "is_geographic": True,
        "source": grid["source"],
        "source_tiles": original_source_tiles,
        "planet": "earth",
        "center_lat": float(candidate["lat"]),
        "grid_metadata": metadata,
    }


# ============================================================
# PLANETARY RASTER WINDOW HELPERS
# ============================================================

def read_window_array(
    src,
    bounds: Tuple[float, float, float, float],
) -> Tuple[np.ndarray, Any]:

    window = from_bounds(
        *bounds,
        transform=src.transform,
    )

    window = (
        window
        .round_offsets()
        .round_lengths()
    )

    full_window = Window(
        0,
        0,
        src.width,
        src.height,
    )

    try:
        window = window.intersection(full_window)
    except WindowError:
        raise ValueError(
            "Requested region is outside raster coverage."
        )

    if window.width < 5 or window.height < 5:
        raise ValueError(
            "Requested region contains too few raster pixels."
        )

    data = src.read(
        1,
        window=window,
        masked=True,
    )

    array = data.astype(
        np.float32
    ).filled(np.nan)

    array[~np.isfinite(array)] = np.nan

    transform = rasterio.windows.transform(
        window,
        src.transform,
    )

    return array, transform


# ============================================================
# PLANETARY RASTER EXTRACTION
# ============================================================

def read_single_raster_window(
    raster_path: Path,
    bounds: Tuple[float, float, float, float],
    planet: str,
    minimum_pixels: int = 5,
) -> Dict[str, Any]:

    west, south, east, north = bounds

    with rasterio.open(raster_path) as src:

        if src.crs is None:
            raise ValueError(
                "Raster has no coordinate reference system."
            )

        if not src.crs.is_geographic:

            raster_bounds = transform_bounds(
                "EPSG:4326",
                src.crs,
                west,
                south,
                east,
                north,
                densify_pts=21,
            )

            array, transform = read_window_array(
                src,
                raster_bounds,
            )

        else:

            raster_west = src.bounds.left
            raster_east = src.bounds.right

            if (
                raster_west >= 0
                and raster_east > 180
            ):
                domain_west = 0.0
                domain_east = 360.0
            else:
                domain_west = -180.0
                domain_east = 180.0

            span = east - west

            if span <= 0 or span >= 360:
                raise ValueError(
                    "Invalid planetary longitude window."
                )

            normalized_west = west
            normalized_east = east

            if domain_west == 0.0:
                normalized_west = west % 360.0
                normalized_east = normalized_west + span

            if normalized_east <= domain_east:

                array, transform = read_window_array(
                    src,
                    (
                        normalized_west,
                        south,
                        normalized_east,
                        north,
                    ),
                )

            else:

                first, first_transform = read_window_array(
                    src,
                    (
                        normalized_west,
                        south,
                        domain_east,
                        north,
                    ),
                )

                second_end = (
                    domain_west
                    + normalized_east
                    - domain_east
                )

                second, _ = read_window_array(
                    src,
                    (
                        domain_west,
                        south,
                        second_end,
                        north,
                    ),
                )

                if first.shape[0] != second.shape[0]:
                    raise ValueError(
                        "Longitude seam windows have incompatible rows."
                    )

                array = np.concatenate(
                    [first, second],
                    axis=1,
                )

                transform = first_transform

        if (
            array.shape[0] < minimum_pixels
            or array.shape[1] < minimum_pixels
        ):
            raise ValueError(
                "Requested region contains too few pixels."
            )

        valid_fraction = float(
            np.count_nonzero(np.isfinite(array))
            / array.size
        )

        if valid_fraction < MIN_VALID_FRACTION:
            raise ValueError(
                f"Insufficient valid {planet.upper()} DEM coverage: "
                f"{valid_fraction:.1%}"
            )

        return {
            "array": array,
            "transform": transform,
            "valid_fraction": valid_fraction,
            "crs": str(src.crs),
            "is_geographic": bool(src.crs.is_geographic),
            "source": str(raster_path),
            "planet": planet,
            "center_lat": (south + north) / 2.0,
        }


# ============================================================
# TERRAIN DESCRIPTOR ENGINE
# ============================================================

def calculate_descriptors(
    raster_data: Dict[str, Any],
    planet: str,
) -> Dict[str, Any]:

    # Work in float32 to reduce memory consumption.
    z = np.asarray(
        raster_data["array"],
        dtype=np.float32,
    )

    valid = np.isfinite(z)

    valid_count = int(
        np.count_nonzero(valid)
    )

    if valid_count < 25:
        raise ValueError(
            "Not enough valid elevation pixels."
        )

    values = z[valid]

    median = float(
        np.median(values)
    )

    mean = float(
        np.mean(values)
    )

    minimum = float(
        np.min(values)
    )

    maximum = float(
        np.max(values)
    )

    relief = maximum - minimum

    elevation_std = float(
        np.std(values)
    )

    transform = raster_data["transform"]

    dx_raw = abs(transform.a)
    dy_raw = abs(transform.e)

    if raster_data.get("is_geographic", False):

        latitude = raster_data["center_lat"]
        body_radius = PLANET_RADII[planet]

        dx = (
            math.radians(dx_raw)
            * body_radius
            * abs(
                math.cos(
                    math.radians(latitude)
                )
            )
        )

        dy = (
            math.radians(dy_raw)
            * body_radius
        )

    else:

        dx = dx_raw
        dy = dy_raw

        try:
            with rasterio.open(
                raster_data["source"]
            ) as src:

                axis_info = src.crs.axis_info

                if axis_info:
                    factor = (
                        axis_info[0].unit_conversion_factor
                    )

                    if factor:
                        dx *= factor
                        dy *= factor

        except Exception:
            logger.warning(
                "Could not determine projected CRS unit conversion."
            )

    dx = max(abs(dx), 0.001)
    dy = max(abs(dy), 0.001)

    # Invalid pixels are filled only for derivative calculations.
    # Original valid pixels remain the statistical mask.
    filled = np.where(
        valid,
        z,
        np.float32(median),
    ).astype(np.float32, copy=False)

    gradient_y, gradient_x = np.gradient(
        filled,
        dy,
        dx,
    )

    slope_radians = np.arctan(
        np.sqrt(
            gradient_x * gradient_x
            + gradient_y * gradient_y
        )
    )

    slope_degrees = np.degrees(
        slope_radians
    )

    slope_valid = slope_degrees[valid]

    # Eight-neighbour local residual roughness.
    padded = np.pad(
        filled,
        1,
        mode="edge",
    )

    neighbors = (
        padded[:-2, :-2]
        + padded[:-2, 1:-1]
        + padded[:-2, 2:]
        + padded[1:-1, :-2]
        + padded[1:-1, 2:]
        + padded[2:, :-2]
        + padded[2:, 1:-1]
        + padded[2:, 2:]
    ) / np.float32(8.0)

    residual = filled - neighbors

    roughness_values = residual[valid]

    roughness = float(
        np.sqrt(
            np.mean(
                roughness_values * roughness_values
            )
        )
    )

    return {
        "elevation_mean": mean,
        "elevation_median": median,
        "elevation_min": minimum,
        "elevation_max": maximum,

        "relief": float(relief),
        "elevation_std": elevation_std,

        "slope_mean": float(
            np.mean(slope_valid)
        ),

        "slope_std": float(
            np.std(slope_valid)
        ),

        "slope_max": float(
            np.max(slope_valid)
        ),

        "roughness": roughness,

        "valid_fraction": raster_data["valid_fraction"],
        "pixel_count": valid_count,

        "pixel_spacing_x_m": float(dx),
        "pixel_spacing_y_m": float(dy),
    }


# ============================================================
# SIMILARITY ENGINE
# ============================================================

DESCRIPTOR_WEIGHTS = {
    "relief": 0.25,
    "slope_mean": 0.25,
    "roughness": 0.25,
    "elevation_std": 0.25,
}


def calculate_similarity(
    target: Dict[str, Any],
    candidate: Dict[str, Any],
) -> Dict[str, Any]:

    differences = {}
    weighted_error = 0.0

    for key, weight in DESCRIPTOR_WEIGHTS.items():

        target_value = float(target[key])
        candidate_value = float(candidate[key])

        difference = abs(
            target_value - candidate_value
        )

        scale = max(
            abs(target_value),
            abs(candidate_value),
            1.0,
        )

        normalized_error = min(
            difference / scale,
            1.0,
        )

        weighted_error += (
            normalized_error * weight
        )

        differences[key] = {
            "target": target_value,
            "candidate": candidate_value,
            "absolute_difference": difference,
            "normalized_difference": normalized_error,
        }

    score = max(
        0.0,
        100.0 * (1.0 - weighted_error),
    )

    return {
        "similarity_score": round(score, 2),
        "parameter_differences": differences,
        "score_interpretation": (
            "Exploratory weighted comparative terrain similarity index; "
            "not a probability, statistical confidence, or validated "
            "measure of geological equivalence."
        ),
    }


# ============================================================
# TARGET ANALYSIS
# ============================================================

def analyse_target(
    planet: str,
    lat: float,
    lon: float,
    radius_km: float,
):

    dem_path = get_planet_dem_path(planet)

    bounds = make_geographic_bounds(
        lat,
        lon,
        radius_km,
        planet,
    )

    raster = read_single_raster_window(
        dem_path,
        bounds,
        planet,
    )

    descriptors = calculate_descriptors(
        raster,
        planet,
    )

    metadata = {
        **get_planetary_provenance(
            planet,
            dem_path,
        ),

        "source_file": str(dem_path),
        "source_crs": raster["crs"],

        "resolution_x": descriptors["pixel_spacing_x_m"],
        "resolution_y": descriptors["pixel_spacing_y_m"],

        "valid_fraction": raster["valid_fraction"],
    }

    return descriptors, metadata


# ============================================================
# EARTH CANDIDATE ANALYSIS
# ============================================================

def analyse_earth_candidate(
    candidate: Dict[str, Any],
    radius_km: float,
):

    raster = read_stored_earth_window(
        candidate,
        radius_km,
    )

    descriptors = calculate_descriptors(
        raster,
        "earth",
    )

    return {
        "descriptors": descriptors,
        "grid_path": raster["source"],
        "source_tiles": raster["source_tiles"],
        "source_crs": raster["crs"],
        "valid_fraction": raster["valid_fraction"],
    }


# ============================================================
# API — ROOT
# ============================================================

@app.get("/")
def root():

    return {
        "name": APP_NAME,
        "version": VERSION,
        "status": "online",
        "message": "VYOMARA Scientific Engine is running.",
    }


# ============================================================
# API — HEALTH
# ============================================================

@app.get("/api/health")
def health():

    moon_available = raster_is_usable(
        MOON_DEM_PATH
    )

    mars_available = raster_is_usable(
        MARS_DEM_PATH
    )

    earth_available = all(
        candidate_grid_path(candidate).exists()
        for candidate in EARTH_SCREENING_POINTS
    )

    earth_grid_count = sum(
        1
        for candidate in EARTH_SCREENING_POINTS
        if candidate_grid_path(candidate).exists()
    )

    return {
        "status": "healthy",
        "engine": APP_NAME,
        "version": VERSION,

        "data_directory": str(DATA_DIR),
        "cache_directory": str(CACHE_DIR),

        "planetary_data": {
            "moon": {
                "available": moon_available,
                "local_file": str(MOON_DEM_PATH),
                "mission": "NASA Lunar Reconnaissance Orbiter",
                "instrument": "LOLA",
                "remote_url_configured": bool(MOON_DEM_URL),
            },

            "mars": {
                "available": mars_available,
                "local_file": str(MARS_DEM_PATH),
                "mission": "NASA Mars Global Surveyor",
                "instrument": "MOLA",
                "remote_url_configured": bool(MARS_DEM_URL),
            },
        },

        "earth_data": {
            **EARTH_PROVENANCE,
            "available": earth_available,
            "stored_grid_count": earth_grid_count,
            "expected_grid_count": len(EARTH_SCREENING_POINTS),
            "grid_directory": str(EARTH_GRID_DIR),
            "grid_radius_km": EARTH_GRID_RADIUS_KM,
            "automatic_tile_retrieval": False,
        },
    }


# ============================================================
# API — PARAMETERS
# ============================================================

@app.get("/api/parameters")
def get_parameters():

    return {
        "parameters": [
            {
                "id": "relief",
                "name": "Terrain Relief",
                "description": (
                    "Elevation range within the analysed region."
                ),
                "unit": "m",
            },
            {
                "id": "slope_mean",
                "name": "Mean Slope",
                "description": "Mean terrain gradient.",
                "unit": "degrees",
            },
            {
                "id": "roughness",
                "name": "Terrain Roughness",
                "description": (
                    "Local elevation residual RMS."
                ),
                "unit": "m",
            },
            {
                "id": "elevation_std",
                "name": "Elevation Variability",
                "description": (
                    "Standard deviation of elevation."
                ),
                "unit": "m",
            },
        ],

        "weights": DESCRIPTOR_WEIGHTS,

        "methodological_warning": (
            "The source DEMs have different native spatial resolutions. "
            "Slope and roughness comparisons are exploratory and require "
            "common-resolution validation."
        ),

        "earth_grid_radius_km": EARTH_GRID_RADIUS_KM,
    }


# ============================================================
# API — REGIONS
# ============================================================

@app.get("/api/regions/{planet}")
def get_regions(planet: str):

    planet = validate_planet(planet)

    if planet == "moon":
        return [
            {
                "id": "shackleton",
                "name": "Shackleton Crater",
                "lat": -89.9,
                "lon": 0.0,
            },
            {
                "id": "tycho",
                "name": "Tycho Crater",
                "lat": -43.31,
                "lon": -11.36,
            },
            {
                "id": "copernicus",
                "name": "Copernicus Crater",
                "lat": 9.62,
                "lon": -20.08,
            },
        ]

    return [
        {
            "id": "jezero",
            "name": "Jezero Crater",
            "lat": 18.38,
            "lon": 77.58,
        },
        {
            "id": "gale",
            "name": "Gale Crater",
            "lat": -5.4,
            "lon": 137.8,
        },
        {
            "id": "olympus",
            "name": "Olympus Mons",
            "lat": 18.65,
            "lon": -133.8,
        },
    ]


# ============================================================
# API — DISCOVERY
# ============================================================

@app.get("/api/discover")
def discover_analogues(
    response: Response,
    planet: str = Query(...),
    lat: float = Query(...),
    lon: float = Query(...),
    radius: float = Query(
        10.0,
        gt=0,
        le=MAX_RADIUS_KM,
    ),
    mode: str = Query("scientific"),
    candidate_id: Optional[str] = Query(None),
):

    planet = validate_planet(planet)

    validate_coordinates(lat, lon)
    validate_radius(radius)

    mode = mode.lower().strip()

    if mode == "demo":
        raise HTTPException(
            status_code=400,
            detail=(
                "Synthetic demo mode is disabled. "
                "Only real DEM-derived results are permitted."
            ),
        )

    if mode != "scientific":
        raise HTTPException(
            status_code=400,
            detail="Unsupported mode. Use 'scientific'.",
        )

    if radius > EARTH_GRID_RADIUS_KM:
        raise HTTPException(
            status_code=400,
            detail=(
                "The stored Earth dataset currently supports "
                f"analysis radii up to {EARTH_GRID_RADIUS_KM:g} km. "
                "Choose a radius at or below this limit."
            ),
        )

    # --------------------------------------------------------
    # CANDIDATE SELECTION
    # --------------------------------------------------------

    candidates = EARTH_SCREENING_POINTS

    if candidate_id:

        candidates = [
            candidate
            for candidate in EARTH_SCREENING_POINTS
            if candidate_identifier(candidate) == candidate_id
        ]

        if not candidates:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown Earth candidate ID: {candidate_id}",
            )

    # --------------------------------------------------------
    # TARGET ANALYSIS
    # --------------------------------------------------------

    try:

        target, target_metadata = analyse_target(
            planet,
            lat,
            lon,
            radius,
        )

    except HTTPException:
        raise

    except Exception as exc:

        logger.exception("Target analysis failed.")

        raise HTTPException(
            status_code=500,
            detail={
                "message": "Target terrain analysis failed.",
                "reason": str(exc),
            },
        )

    results = []
    failures = []

    # --------------------------------------------------------
    # EARTH CANDIDATE ANALYSIS
    # --------------------------------------------------------

    for candidate in candidates:

        try:

            earth_data = analyse_earth_candidate(
                candidate,
                radius,
            )

            candidate_descriptors = (
                earth_data["descriptors"]
            )

            comparison = calculate_similarity(
                target,
                candidate_descriptors,
            )

            completeness = min(
                target["valid_fraction"],
                candidate_descriptors["valid_fraction"],
            )

            result = {

                "id": candidate_identifier(candidate),

                "location_name": candidate["name"],
                "country": candidate["country"],

                "latitude": candidate["lat"],
                "longitude": candidate["lon"],

                "lat": candidate["lat"],
                "lon": candidate["lon"],

                "target_completeness": round(
                    target["valid_fraction"] * 100,
                    2,
                ),

                "candidate_completeness": round(
                    candidate_descriptors["valid_fraction"] * 100,
                    2,
                ),

                "descriptors": candidate_descriptors,

                "target_descriptors": target,

                "elevation_stats": {
                    "target": {
                        "mean": target["elevation_mean"],
                        "relief": target["relief"],
                        "std": target["elevation_std"],
                    },

                    "candidate": {
                        "mean": candidate_descriptors["elevation_mean"],
                        "relief": candidate_descriptors["relief"],
                        "std": candidate_descriptors["elevation_std"],
                    },
                },

                "parameter_differences": (
                    comparison["parameter_differences"]
                ),

                "similarity_score": (
                    comparison["similarity_score"]
                ),

                "score_interpretation": (
                    comparison["score_interpretation"]
                ),

                "data_sources": {

                    "target": target_metadata,

                    "candidate": {
                        **EARTH_PROVENANCE,

                        "files": [
                            earth_data["grid_path"]
                        ],

                        "original_source_tiles": (
                            earth_data["source_tiles"]
                        ),

                        "crs": earth_data["source_crs"],

                        "grid_metadata": {
                            "radius_km": EARTH_GRID_RADIUS_KM,
                            "storage": "compressed_npz",
                        },
                    },
                },

                "mode": "scientific",
                "status": "computed",

                "quality": {
                    "minimum_valid_fraction": round(
                        completeness,
                        4,
                    ),

                    "interpretation": (
                        "Data completeness indicator; "
                        "not statistical confidence."
                    ),
                },

                "methodology": {

                    "score_type": (
                        "exploratory_comparative_index"
                    ),

                    "score_is_probability": False,

                    "common_resolution_resampling": False,

                    "native_resolution_comparison_warning": (
                        "Source DEM resolutions differ. "
                        "Slope and roughness are scale-dependent."
                    ),

                    "elevation_included_in_score": False,

                    "earth_grid_storage": "pre-extracted_npz",

                    "runtime_copernicus_retrieval": False,
                },
            }

            results.append(result)

        except Exception as exc:

            failures.append({
                "candidate": candidate["name"],
                "reason": str(exc),
            })

            logger.warning(
                "Candidate skipped: %s — %s",
                candidate["name"],
                exc,
            )

    # --------------------------------------------------------
    # RESULT VALIDATION
    # --------------------------------------------------------

    if not results:
        raise HTTPException(
            status_code=503,
            detail={
                "message": (
                    "No Earth analogue candidates could be analysed."
                ),

                "failed_candidates": failures,

                "suggestion": (
                    "Check the stored Earth grids in data/earth_grids "
                    "and verify that the target planetary DEM is available."
                ),
            },
        )

    results.sort(
        key=lambda item: item["similarity_score"],
        reverse=True,
    )

    # Preserve the existing JSON array response.
    response.headers[
        "X-Vyomara-Candidate-Count"
    ] = str(len(results))

    response.headers[
        "X-Vyomara-Failed-Candidates"
    ] = str(len(failures))

    response.headers[
        "X-Vyomara-Search-Method"
    ] = "predefined_candidate_screening"

    response.headers[
        "X-Vyomara-Exhaustive-Global-Search"
    ] = "false"

    response.headers[
        "X-Vyomara-Partial-Results"
    ] = "true" if failures else "false"

    response.headers[
        "X-Vyomara-Earth-Data-Source"
    ] = "stored_copernicus_grids"

    return results


# ============================================================
# API — DISCOVERY STATUS
# ============================================================

@app.get("/api/discover/status")
def discovery_status():

    available_count = sum(
        1
        for candidate in EARTH_SCREENING_POINTS
        if candidate_grid_path(candidate).exists()
    )

    return {

        "version": VERSION,

        "search_method": "predefined_candidate_screening",

        "candidate_count": len(EARTH_SCREENING_POINTS),

        "available_grid_count": available_count,

        "exhaustive_global_search": False,

        "earth_dataset": "Copernicus DEM GLO-90",

        "earth_dataset_type": "Digital Surface Model",

        "earth_grid_storage": "compressed_npz",

        "earth_grid_directory": str(EARTH_GRID_DIR),

        "earth_grid_radius_km": EARTH_GRID_RADIUS_KM,

        "runtime_copernicus_retrieval": False,

        "planetary_sources": {
            "moon": PLANETARY_PROVENANCE["moon"],
            "mars": PLANETARY_PROVENANCE["mars"],
        },

        "cache_enabled": True,

        "synthetic_data": False,

        "similarity_method": (
            "Weighted normalized terrain descriptor comparison"
        ),

        "similarity_is_probability": False,

        "descriptor_weights": DESCRIPTOR_WEIGHTS,

        "common_resolution_resampling": False,

        "known_limitations": [

            "Earth search uses 18 predefined candidate regions.",

            "Results are not an exhaustive global ranking.",

            "Earth grids currently cover a maximum 10 km radius.",

            "Similarity scores are exploratory comparative indices.",

            "Scores are not probabilities or statistical confidence.",

            "Planetary and Earth vertical reference systems differ.",

            "Native DEM resolutions differ substantially.",

            "Slope and roughness are resolution-dependent.",

            "Common-resolution resampling is not yet implemented.",

            "Copernicus GLO-90 is a Digital Surface Model.",

            "The scoring method requires scientific validation.",
        ],
    }


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
def startup_event():

    available_grids = sum(
        1
        for candidate in EARTH_SCREENING_POINTS
        if candidate_grid_path(candidate).exists()
    )

    logger.info("=" * 60)
    logger.info("VYOMARA SCIENTIFIC ENGINE")
    logger.info("Version %s", VERSION)
    logger.info("Backend started.")
    logger.info("Data directory: %s", DATA_DIR)
    logger.info("Earth grid directory: %s", EARTH_GRID_DIR)

    logger.info(
        "Moon DEM usable: %s",
        raster_is_usable(MOON_DEM_PATH),
    )

    logger.info(
        "Mars DEM usable: %s",
        raster_is_usable(MARS_DEM_PATH),
    )

    logger.info(
        "Earth stored grids: %s/%s",
        available_grids,
        len(EARTH_SCREENING_POINTS),
    )

    logger.info(
        "Earth grid radius: %s km",
        EARTH_GRID_RADIUS_KM,
    )

    logger.info(
        "Search type: predefined candidate screening"
    )

    logger.info(
        "Earth runtime tile retrieval: disabled"
    )

    logger.info(
        "Planetary DEM download concurrency protection: enabled"
    )

    logger.info("Synthetic data: disabled")
    logger.info("=" * 60)
