"""
Unified Image Analyzer for Delivery Proof Photos

Combines GPS extraction, quality checking, and AI vision analysis
into one streamlined service.
"""

from PIL import Image, ImageStat, ImageFilter
from PIL.ExifTags import TAGS, GPSTAGS
from datetime import datetime
from typing import Dict, Optional, Tuple
import os
import json


# ==================== GPS / EXIF Metadata Extraction ====================

def extract_gps_metadata(image_path: str) -> Dict:
    """
    Extract GPS coordinates and EXIF metadata from image.
    GPS data is voluntary - if not present, noted as unverified.

    Args:
        image_path: Path to image file

    Returns:
        Dictionary with GPS and metadata info
    """
    result = {
        'has_gps': False,
        'gps_latitude': None,
        'gps_longitude': None,
        'gps_note': 'GPS data not found - location not verified',
        'image_timestamp': None,
        'camera_make': None,
        'camera_model': None
    }

    try:
        image = Image.open(image_path)
        exif_data = image._getexif()

        if not exif_data:
            result['gps_note'] = 'No EXIF data found - location not verified'
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

                # Parse GPS coordinates
                lat, lon = _parse_gps_coords(gps_data)
                if lat is not None and lon is not None:
                    result['has_gps'] = True
                    result['gps_latitude'] = lat
                    result['gps_longitude'] = lon
                    result['gps_note'] = f'GPS verified: {lat:.6f}, {lon:.6f}'

    except Exception as e:
        result['gps_note'] = f'Error reading metadata: {str(e)}'

    return result


def _parse_gps_coords(gps_data: Dict) -> Tuple[Optional[float], Optional[float]]:
    """Parse GPS coordinates from EXIF GPS data."""
    try:
        if 'GPSLatitude' not in gps_data or 'GPSLongitude' not in gps_data:
            return None, None
        if 'GPSLatitudeRef' not in gps_data or 'GPSLongitudeRef' not in gps_data:
            return None, None

        # Convert from degrees/minutes/seconds to decimal
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
    """Convert GPS coordinate from DMS to decimal degrees."""
    d = float(value[0])
    m = float(value[1])
    s = float(value[2])
    return d + (m / 60.0) + (s / 3600.0)


# ==================== Image Quality Checking ====================

def check_image_quality(image_path: str) -> Dict:
    """
    Check if image meets quality standards (resolution, sharpness, brightness).

    Args:
        image_path: Path to image file

    Returns:
        Dictionary with quality assessment
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
        image = Image.open(image_path)
        width, height = image.size
        result['resolution'] = f"{width}x{height}"
        result['file_size'] = os.path.getsize(image_path)

        # Check resolution
        min_width, min_height = 640, 480
        if width < min_width or height < min_height:
            result['is_acceptable'] = False
            result['quality_score'] -= 30
            result['issues'].append(f'Resolution too low ({width}x{height})')

        # Check file size
        if result['file_size'] < 50000:  # 50KB
            result['warnings'].append('File size very small - may be low quality')
            result['quality_score'] -= 10

        # Analyze brightness
        grayscale = image.convert('L')
        stat = ImageStat.Stat(grayscale)
        brightness = stat.mean[0]

        if brightness < 30:
            result['is_too_dark'] = True
            result['is_acceptable'] = False
            result['quality_score'] -= 25
            result['issues'].append('Image too dark - retake in better lighting')
        elif brightness < 60:
            result['warnings'].append('Image somewhat dark')
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
            result['issues'].append('Image too blurry - hold camera steady')
        elif blur_score < 100:
            result['warnings'].append('Image may be slightly blurry')
            result['quality_score'] -= 15

        # Final score check
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
    """
    try:
        edges = grayscale_image.filter(ImageFilter.FIND_EDGES)
        stat = ImageStat.Stat(edges)
        blur_score = stat.stddev[0] * 10  # Scale to reasonable range
        return float(blur_score)
    except:
        return 100.0


# ==================== AI Vision Analysis (BLIP) ====================

class VisionAnalyzer:
    """Lazy-loaded vision model for analyzing delivery proof photos."""

    _instance = None
    _model = None
    _processor = None
    _model_loaded = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(VisionAnalyzer, cls).__new__(cls)
        return cls._instance

    def is_available(self) -> bool:
        """Check if vision model is available."""
        return self._model_loaded

    def load_model(self):
        """Load BLIP vision model (lazy loading)."""
        if self._model_loaded:
            return

        try:
            print("[Vision] Loading BLIP vision model (first time only)...")
            from transformers import BlipProcessor, BlipForConditionalGeneration

            model_id = "Salesforce/blip-image-captioning-base"

            self._processor = BlipProcessor.from_pretrained(model_id)
            self._model = BlipForConditionalGeneration.from_pretrained(
                model_id,
                low_cpu_mem_usage=True
            )

            self._model_loaded = True
            print("[Vision] Model loaded successfully!")

        except Exception as e:
            print(f"[Vision] Failed to load model: {e}")
            self._model_loaded = False

    def analyze_photo(self, image_path: str, order_description: str = None) -> Dict:
        """
        Analyze delivery proof photo using AI vision (BLIP).

        Args:
            image_path: Path to photo
            order_description: Optional order description for context

        Returns:
            Dictionary with AI analysis results
        """
        if not self._model_loaded:
            self.load_model()

        if not self._model_loaded:
            return {
                'description': 'Vision analysis unavailable',
                'is_legitimate': True,  # Default to true if model fails
                'confidence': 0,
                'flags': ['Model not loaded'],
                'matches_order': None,
                'raw_answers': []
            }

        try:
            image = Image.open(image_path).convert('RGB')

            # Generate unconditional caption (what the model sees)
            inputs = self._processor(image, return_tensors="pt")
            caption_output = self._model.generate(**inputs, max_new_tokens=50)
            caption = self._processor.decode(caption_output[0], skip_special_tokens=True)

            # Generate conditional captions with prompts
            prompts = [
                "a photo of",
                "this is a delivery photo showing",
                "package or food at"
            ]

            conditional_captions = []
            for prompt in prompts:
                inputs = self._processor(image, text=prompt, return_tensors="pt")
                output = self._model.generate(**inputs, max_new_tokens=30)
                cond_caption = self._processor.decode(output[0], skip_special_tokens=True)
                conditional_captions.append(cond_caption)

            # Combine all outputs
            all_answers = [caption] + conditional_captions

            # Analyze the caption for delivery-related keywords
            caption_lower = caption.lower()
            delivery_keywords = ['box', 'package', 'food', 'door', 'doorstep', 'delivery',
                               'bag', 'pizza', 'burger', 'meal', 'envelope', 'parcel']

            has_delivery_keyword = any(kw in caption_lower for kw in delivery_keywords)

            # Calculate confidence
            confidence = 60  # Base confidence
            flags = []

            if has_delivery_keyword:
                confidence += 20
            else:
                flags.append('No clear delivery item visible')
                confidence -= 20

            # Simple heuristics for quality
            if len(caption.split()) < 3:
                flags.append('Low detail in image')
                confidence -= 10

            # Check order match if provided
            matches_order = None
            if order_description:
                desc_lower = order_description.lower()
                # Check if any words from order description appear in caption
                order_words = [w for w in desc_lower.split() if len(w) > 3]
                matching_words = sum(1 for word in order_words if word in caption_lower)
                if matching_words > 0:
                    matches_order = True
                    confidence += 10

            return {
                'description': caption.capitalize(),
                'is_legitimate': confidence >= 50,
                'confidence': min(95, max(5, confidence)),  # Clamp 5-95
                'flags': flags,
                'matches_order': matches_order,
                'raw_answers': all_answers
            }

        except Exception as e:
            print(f"[Vision] Error analyzing photo: {e}")
            return {
                'description': f'Analysis failed: {str(e)}',
                'is_legitimate': True,
                'confidence': 0,
                'flags': ['Analysis error'],
                'matches_order': None,
                'raw_answers': []
            }


# Global instance
_vision_analyzer = VisionAnalyzer()


# ==================== Main Analysis Function ====================

def analyze_delivery_photo(image_path: str, order_description: str = None, use_ai_vision: bool = True) -> Dict:
    """
    Complete analysis of delivery proof photo.

    Args:
        image_path: Path to uploaded photo
        order_description: Optional order items description
        use_ai_vision: Whether to use AI vision analysis (default True)

    Returns:
        Complete analysis dictionary
    """
    result = {
        'success': True,
        'image_path': image_path,
        'gps': {},
        'quality': {},
        'vision': {},
        'summary': '',
        'warnings': [],
        'errors': []
    }

    try:
        # Step 1: Extract GPS metadata
        print(f"[Image Analysis] Extracting GPS metadata...")
        result['gps'] = extract_gps_metadata(image_path)

        # Step 2: Check image quality
        print(f"[Image Analysis] Checking image quality...")
        result['quality'] = check_image_quality(image_path)

        if not result['quality']['is_acceptable']:
            result['warnings'].append('Image quality is poor')

        # Step 3: AI Vision analysis
        if use_ai_vision:
            print(f"[Image Analysis] Running AI vision analysis...")
            result['vision'] = _vision_analyzer.analyze_photo(image_path, order_description)

            if not result['vision']['is_legitimate']:
                result['warnings'].append('AI flagged potential issues')
        else:
            result['vision'] = {
                'description': 'AI vision disabled',
                'is_legitimate': True,
                'confidence': 0,
                'flags': [],
                'matches_order': None
            }

        # Generate summary
        result['summary'] = _generate_summary(result)

        print(f"[Image Analysis] Complete: {result['summary']}")

    except Exception as e:
        result['success'] = False
        result['errors'].append(f'Analysis error: {str(e)}')
        result['summary'] = f'Failed: {str(e)}'
        print(f"[Image Analysis] Error: {str(e)}")

    return result


def _generate_summary(result: Dict) -> str:
    """Generate human-readable summary."""
    parts = []

    # Quality
    quality = result['quality']
    if quality['is_acceptable']:
        if quality['quality_score'] >= 90:
            parts.append("Excellent quality")
        elif quality['quality_score'] >= 75:
            parts.append("Good quality")
        else:
            parts.append("Acceptable quality")
    else:
        parts.append("Poor quality")

    # GPS
    if result['gps']['has_gps']:
        parts.append("GPS verified")
    else:
        parts.append("GPS not verified")

    # AI Vision
    if result['vision'].get('confidence', 0) > 0:
        conf = result['vision']['confidence']
        if conf >= 80:
            parts.append(f"AI confident ({conf}%)")
        elif conf >= 50:
            parts.append(f"AI moderate ({conf}%)")
        else:
            parts.append(f"AI suspicious ({conf}%)")

    return " | ".join(parts)


def get_analysis_for_db(result: Dict) -> Dict:
    """
    Convert analysis result to clean dictionary for database storage.

    Args:
        result: Analysis result from analyze_delivery_photo()

    Returns:
        Clean dictionary suitable for JSON field
    """
    return {
        'gps_verified': result['gps']['has_gps'],
        'gps_latitude': result['gps']['gps_latitude'],
        'gps_longitude': result['gps']['gps_longitude'],
        'gps_note': result['gps']['gps_note'],
        'image_timestamp': result['gps']['image_timestamp'].isoformat() if result['gps']['image_timestamp'] else None,
        'camera_make': result['gps']['camera_make'],
        'camera_model': result['gps']['camera_model'],
        'quality_score': result['quality']['quality_score'],
        'quality_acceptable': result['quality']['is_acceptable'],
        'quality_issues': result['quality']['issues'],
        'ai_description': result['vision'].get('description', 'N/A'),
        'ai_confidence': result['vision'].get('confidence', 0),
        'ai_legitimate': result['vision'].get('is_legitimate', True),
        'ai_flags': result['vision'].get('flags', []),
        'ai_raw_answers': result['vision'].get('raw_answers', []),
        'summary': result['summary']
    }
