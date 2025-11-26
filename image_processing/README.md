# Image Processing Module

Automated processing for delivery proof photos with GPS verification, quality checking, and privacy protection.

## Features

### 1. GPS/EXIF Metadata Extraction (Voluntary)
- Extracts GPS coordinates from photo EXIF data
- Extracts timestamp information
- **Important**: GPS data is voluntary - if not present, a note is saved: *"GPS data not found in image - location not verified"*
- Helps verify courier was at the delivery location
- Prevents fraud

### 2. Image Quality Validation
- Checks image resolution (minimum 640x480)
- Detects blurry images using Laplacian variance
- Analyzes brightness (too dark or too bright)
- Assigns quality score (0-100)
- Warns courier if image quality is poor

### 3. Privacy Protection (Face Blurring)
- Automatically detects faces in delivery proof photos
- Blurs faces to protect privacy
- GDPR/privacy compliant
- **Note**: Basic implementation included; see setup for advanced options

## Installation

### Basic Setup (Included)
```bash
pip install -r requirements.txt
```

This installs:
- `Pillow` - Image processing
- `numpy` - Numerical operations

### Advanced Face Detection (Optional)

For better face detection, install OpenCV:
```bash
pip install opencv-python
```

Then update `privacy_protector.py` to use OpenCV's Haar Cascades (see comments in file).

## Module Structure

```
image_processing/
├── __init__.py              # Module exports
├── processor.py             # Main coordinator
├── metadata_extractor.py    # GPS/EXIF extraction
├── quality_checker.py       # Image quality validation
├── privacy_protector.py     # Face blurring
└── README.md               # This file
```

## How It Works

When a courier uploads a delivery proof photo, the system automatically:

1. **Saves the photo** to `static/uploads/`
2. **Processes the image** through:
   - Metadata extraction (GPS optional)
   - Quality check
   - Privacy protection
3. **Stores analysis** in database (JSON field)
4. **Displays results** in order view pages

## Usage

```python
from image_processing import process_delivery_image

# Process an uploaded image
result = process_delivery_image(
    image_path='path/to/image.jpg',
    apply_privacy_protection=True  # Blur faces
)

# Result contains:
# - metadata: GPS coordinates, timestamps, camera info
# - quality: Quality score, issues, warnings
# - privacy: Faces detected and blurred
# - summary: Human-readable summary
```

## GPS Data Policy

**GPS data is completely voluntary:**
- If photo has GPS data → Extracted and verified
- If photo lacks GPS data → Noted as "GPS not verified"
- Both cases are acceptable
- No penalty for missing GPS data
- Courier privacy is protected

This allows:
- Couriers to choose whether to share location
- System to note when verification isn't possible
- Flexibility for different devices/settings

## Database Storage

Analysis results are stored in the `Order.delivery_proof_analysis` JSON field:

```json
{
  "gps_verified": false,
  "gps_latitude": null,
  "gps_longitude": null,
  "gps_note": "GPS data not found in image - location not verified",
  "quality_score": 85,
  "quality_acceptable": true,
  "quality_issues": [],
  "faces_blurred": 0,
  "summary": "Good quality image | GPS not verified"
}
```

## UI Display

The analysis is displayed on order view pages with color-coded indicators:

- 🟢 **Green** - GPS verified, good quality
- 🟡 **Yellow** - No GPS data (acceptable)
- 🔴 **Red** - Poor image quality
- 🔵 **Blue** - Privacy protection applied

## Future Enhancements

Potential improvements:

1. **License Plate Detection & Blurring**
   - OCR + pattern matching
   - Automatic blur like faces

2. **Geocoding Integration**
   - Verify GPS coordinates match delivery address
   - Google Maps API / OpenStreetMap

3. **Duplicate Image Detection**
   - Prevent couriers from reusing photos
   - Perceptual hashing

4. **Screenshot Detection**
   - Detect if image is screenshot vs real photo
   - Prevent fraud

5. **Cloud AI Services**
   - Google Vision API
   - AWS Rekognition
   - More accurate detection

## Error Handling

The module is designed to fail gracefully:
- If processing fails, upload still succeeds
- Error is logged in analysis JSON
- System remains functional
- No blocking of critical operations

## Testing

To test the image processing:

1. Upload a delivery proof photo with GPS data (smartphone photo)
2. Check order view page for analysis results
3. Verify GPS coordinates are extracted
4. Check image quality score
5. Confirm faces are blurred (if present)

## Support

For issues or questions:
- Check module comments for implementation details
- Review error logs in database
- See inline comments for OpenCV integration

---

**Note**: This module is self-contained and can be modified independently without affecting the main courier system.
