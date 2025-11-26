"""
Image Processing Module for Delivery Proof Photos

This module provides automated processing for delivery proof images:
- GPS/EXIF metadata extraction (voluntary)
- Image quality validation
- Privacy protection (face blurring)
"""

from .processor import process_delivery_image

__all__ = ['process_delivery_image']
