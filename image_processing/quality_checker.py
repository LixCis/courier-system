"""
Image Quality Checker

Validates that delivery proof images meet minimum quality standards:
- Not too blurry
- Adequate brightness
- Sufficient resolution
- Valid format
"""

from PIL import Image, ImageStat, ImageFilter
from typing import Dict


def check_image_quality(image_path: str) -> Dict:
    """
    Check if image meets quality standards for delivery proof.

    Args:
        image_path: Path to the image file

    Returns:
        Dictionary with quality check results
    """
    result = {
        'is_acceptable': True,
        'quality_score': 100,
        'issues': [],
        'warnings': [],
        'resolution': None,
        'file_size': None,
        'is_blurry': False,
        'is_too_dark': False,
        'is_too_bright': False
    }

    try:
        # Open image
        image = Image.open(image_path)
        width, height = image.size
        result['resolution'] = f"{width}x{height}"

        # Get file size
        import os
        result['file_size'] = os.path.getsize(image_path)

        # Check resolution
        min_width, min_height = 640, 480
        if width < min_width or height < min_height:
            result['is_acceptable'] = False
            result['quality_score'] -= 30
            result['issues'].append(f'Resolution too low ({width}x{height}). Minimum: {min_width}x{min_height}')

        # Check if image is too small (file size)
        if result['file_size'] < 50000:  # 50KB
            result['warnings'].append('Image file size is very small - may be low quality')
            result['quality_score'] -= 10

        # Convert to grayscale for analysis
        grayscale = image.convert('L')

        # Check brightness using Pillow's ImageStat
        stat = ImageStat.Stat(grayscale)
        brightness = stat.mean[0]  # Average brightness
        if brightness < 30:
            result['is_too_dark'] = True
            result['is_acceptable'] = False
            result['quality_score'] -= 25
            result['issues'].append('Image is too dark - retake in better lighting')
        elif brightness < 60:
            result['warnings'].append('Image is somewhat dark')
            result['quality_score'] -= 10
        elif brightness > 230:
            result['is_too_bright'] = True
            result['warnings'].append('Image may be overexposed')
            result['quality_score'] -= 10

        # Check blur using edge detection
        blur_score = _calculate_blur_score(grayscale)
        result['blur_score'] = float(blur_score)

        if blur_score < 50:
            result['is_blurry'] = True
            result['is_acceptable'] = False
            result['quality_score'] -= 35
            result['issues'].append('Image is too blurry - hold camera steady and retake')
        elif blur_score < 100:
            result['warnings'].append('Image may be slightly blurry')
            result['quality_score'] -= 15

        # Final quality assessment
        if result['quality_score'] < 50:
            result['is_acceptable'] = False

    except Exception as e:
        result['is_acceptable'] = False
        result['quality_score'] = 0
        result['issues'].append(f'Error analyzing image: {str(e)}')

    return result


def _calculate_blur_score(grayscale_image: Image.Image) -> float:
    """
    Calculate blur score using edge detection.
    Higher score = sharper image.

    Args:
        grayscale_image: Grayscale PIL Image

    Returns:
        Blur score (higher is better)
    """
    try:
        # Apply edge detection filter (similar to Laplacian)
        edges = grayscale_image.filter(ImageFilter.FIND_EDGES)

        # Calculate statistics on the edge-detected image
        stat = ImageStat.Stat(edges)

        # Use standard deviation as blur metric
        # Higher std dev = more edges = sharper image
        blur_score = stat.stddev[0] * 10  # Scale to reasonable range

        return float(blur_score)
    except:
        # If calculation fails, return a neutral score
        return 100.0


def get_quality_summary(quality_result: Dict) -> str:
    """
    Generate human-readable summary of quality check.

    Args:
        quality_result: Result from check_image_quality()

    Returns:
        Summary string
    """
    if quality_result['is_acceptable']:
        if quality_result['quality_score'] >= 90:
            return "Excellent quality image"
        elif quality_result['quality_score'] >= 75:
            return "Good quality image"
        else:
            return "Acceptable quality image"
    else:
        return "Poor quality - " + "; ".join(quality_result['issues'])
