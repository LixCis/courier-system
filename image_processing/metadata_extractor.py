"""
EXIF/GPS Metadata Extractor

Extracts GPS coordinates and timestamp from image EXIF data.
GPS data is VOLUNTARY - if not present, a note is added to the analysis.
"""

from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from datetime import datetime
from typing import Dict, Optional, Tuple


def extract_metadata(image_path: str) -> Dict:
    """
    Extract EXIF metadata including GPS data and timestamps from image.

    Args:
        image_path: Path to the image file

    Returns:
        Dictionary containing metadata and GPS information
    """
    result = {
        'has_gps': False,
        'gps_latitude': None,
        'gps_longitude': None,
        'gps_timestamp': None,
        'image_timestamp': None,
        'camera_make': None,
        'camera_model': None,
        'gps_note': 'GPS data not found in image - location not verified'
    }

    try:
        image = Image.open(image_path)
        exif_data = image._getexif()

        if not exif_data:
            result['gps_note'] = 'No EXIF data found in image - location not verified'
            return result

        # Extract basic EXIF data
        for tag_id, value in exif_data.items():
            tag = TAGS.get(tag_id, tag_id)

            if tag == 'DateTime':
                try:
                    result['image_timestamp'] = datetime.strptime(value, '%Y:%m:%d %H:%M:%S')
                except:
                    pass
            elif tag == 'Make':
                result['camera_make'] = str(value).strip()
            elif tag == 'Model':
                result['camera_model'] = str(value).strip()
            elif tag == 'GPSInfo':
                gps_data = {}
                for gps_tag_id in value:
                    gps_tag = GPSTAGS.get(gps_tag_id, gps_tag_id)
                    gps_data[gps_tag] = value[gps_tag_id]

                # Extract GPS coordinates
                lat, lon = _parse_gps_coordinates(gps_data)
                if lat is not None and lon is not None:
                    result['has_gps'] = True
                    result['gps_latitude'] = lat
                    result['gps_longitude'] = lon
                    result['gps_note'] = f'GPS verified: {lat:.6f}, {lon:.6f}'

                    # Extract GPS timestamp
                    if 'GPSDateStamp' in gps_data and 'GPSTimeStamp' in gps_data:
                        try:
                            date_str = gps_data['GPSDateStamp']
                            time_parts = gps_data['GPSTimeStamp']
                            time_str = f"{int(time_parts[0]):02d}:{int(time_parts[1]):02d}:{int(time_parts[2]):02d}"
                            result['gps_timestamp'] = datetime.strptime(f"{date_str} {time_str}", '%Y:%m:%d %H:%M:%S')
                        except:
                            pass

    except Exception as e:
        result['gps_note'] = f'Error reading image metadata: {str(e)}'

    return result


def _parse_gps_coordinates(gps_data: Dict) -> Tuple[Optional[float], Optional[float]]:
    """
    Parse GPS coordinates from EXIF GPS data.

    Args:
        gps_data: Dictionary containing GPS EXIF tags

    Returns:
        Tuple of (latitude, longitude) or (None, None) if not available
    """
    try:
        if 'GPSLatitude' not in gps_data or 'GPSLongitude' not in gps_data:
            return None, None

        if 'GPSLatitudeRef' not in gps_data or 'GPSLongitudeRef' not in gps_data:
            return None, None

        # Convert GPS coordinates from degrees/minutes/seconds to decimal
        lat = _convert_to_degrees(gps_data['GPSLatitude'])
        if gps_data['GPSLatitudeRef'] == 'S':
            lat = -lat

        lon = _convert_to_degrees(gps_data['GPSLongitude'])
        if gps_data['GPSLongitudeRef'] == 'W':
            lon = -lon

        return lat, lon
    except:
        return None, None


def _convert_to_degrees(value) -> float:
    """
    Convert GPS coordinates from degrees/minutes/seconds to decimal degrees.

    Args:
        value: GPS coordinate in DMS format

    Returns:
        Decimal degrees
    """
    d = float(value[0])
    m = float(value[1])
    s = float(value[2])
    return d + (m / 60.0) + (s / 3600.0)


def verify_location(gps_lat: float, gps_lon: float, delivery_address: str, tolerance_meters: float = 100) -> bool:
    """
    Verify if GPS coordinates are within acceptable distance of delivery address.

    Note: This is a placeholder. Real implementation would need geocoding service.

    Args:
        gps_lat: GPS latitude from image
        gps_lon: GPS longitude from image
        delivery_address: Delivery address string
        tolerance_meters: Acceptable distance in meters

    Returns:
        True if location matches, False otherwise
    """
    # TODO: Implement with geocoding service (Google Maps API, OpenStreetMap, etc.)
    # For now, just return True if GPS data exists
    return gps_lat is not None and gps_lon is not None
