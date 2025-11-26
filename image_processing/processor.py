"""
Main Image Processor

Coordinates all image processing tasks for delivery proof photos:
1. Extract GPS/EXIF metadata (voluntary)
2. Check image quality
3. Apply privacy protection (blur faces)
"""

from typing import Dict
import json
from .metadata_extractor import extract_metadata
from .quality_checker import check_image_quality, get_quality_summary
from .privacy_protector import blur_faces


def process_delivery_image(image_path: str, apply_privacy_protection: bool = True) -> Dict:
    """
    Process a delivery proof image through all analysis and protection steps.

    Args:
        image_path: Path to the uploaded delivery proof image
        apply_privacy_protection: Whether to blur faces (default: True)

    Returns:
        Dictionary containing all analysis results
    """
    result = {
        'success': True,
        'image_path': image_path,
        'metadata': {},
        'quality': {},
        'privacy': {},
        'summary': '',
        'warnings': [],
        'errors': []
    }

    try:
        # Step 1: Extract metadata (GPS is voluntary)
        print(f"[Image Processing] Extracting metadata from {image_path}...")
        result['metadata'] = extract_metadata(image_path)

        # Step 2: Check image quality
        print(f"[Image Processing] Checking image quality...")
        result['quality'] = check_image_quality(image_path)

        if not result['quality']['is_acceptable']:
            result['warnings'].append('Image quality is poor - consider retaking')

        # Step 3: Apply privacy protection (blur faces)
        if apply_privacy_protection:
            print(f"[Image Processing] Applying privacy protection...")
            result['privacy'] = blur_faces(image_path)
        else:
            result['privacy'] = {
                'faces_detected': 0,
                'faces_blurred': 0,
                'privacy_protected': False,
                'note': 'Privacy protection skipped'
            }

        # Generate summary
        result['summary'] = _generate_summary(result)

        print(f"[Image Processing] Complete: {result['summary']}")

    except Exception as e:
        result['success'] = False
        result['errors'].append(f'Processing error: {str(e)}')
        result['summary'] = f'Image processing failed: {str(e)}'
        print(f"[Image Processing] Error: {str(e)}")

    return result


def _generate_summary(result: Dict) -> str:
    """
    Generate human-readable summary of image processing.

    Args:
        result: Processing result dictionary

    Returns:
        Summary string
    """
    parts = []

    # Quality summary
    quality_summary = get_quality_summary(result['quality'])
    parts.append(quality_summary)

    # GPS summary
    if result['metadata']['has_gps']:
        parts.append(f"GPS verified at ({result['metadata']['gps_latitude']:.6f}, {result['metadata']['gps_longitude']:.6f})")
    else:
        parts.append(result['metadata']['gps_note'])

    # Privacy summary
    if result['privacy']['privacy_protected']:
        parts.append(f"{result['privacy']['faces_blurred']} face(s) blurred for privacy")

    return " | ".join(parts)


def get_analysis_json(result: Dict) -> str:
    """
    Convert analysis result to JSON string for database storage.

    Args:
        result: Processing result dictionary

    Returns:
        JSON string
    """
    # Create a clean version for database storage
    db_data = {
        'gps_verified': result['metadata']['has_gps'],
        'gps_lat': result['metadata']['gps_latitude'],
        'gps_lon': result['metadata']['gps_longitude'],
        'gps_note': result['metadata']['gps_note'],
        'quality_score': result['quality']['quality_score'],
        'quality_acceptable': result['quality']['is_acceptable'],
        'quality_issues': result['quality']['issues'],
        'faces_blurred': result['privacy']['faces_blurred'],
        'image_timestamp': result['metadata']['image_timestamp'].isoformat() if result['metadata']['image_timestamp'] else None,
        'camera_make': result['metadata']['camera_make'],
        'camera_model': result['metadata']['camera_model'],
        'summary': result['summary']
    }

    return json.dumps(db_data, ensure_ascii=False)
