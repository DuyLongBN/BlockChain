"""
Utility functions for license plate recognition system
"""
import cv2
import numpy as np
import os
from pathlib import Path
import config


def create_directories():
    """Create necessary directories if they don't exist"""
    directories = [
        config.DATA_RAW_PATH,
        config.DATA_PROCESSED_PATH,
        config.MODELS_PATH,
        config.RESULTS_PATH
    ]
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)


def load_image(image_path):
    """Load image from file"""
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Unable to load image from {image_path}")
    return img


def save_image(image_path, image):
    """Save image to file"""
    cv2.imwrite(image_path, image)


def resize_image(image, width=None, height=None, inter=cv2.INTER_AREA):
    """Resize image maintaining aspect ratio"""
    (h, w) = image.shape[:2]
    
    if width is None and height is None:
        return image
    
    if width is None:
        r = height / float(h)
        dim = (int(w * r), height)
    else:
        r = width / float(w)
        dim = (width, int(h * r))
    
    return cv2.resize(image, dim, interpolation=inter)


def display_image(title, image):
    """Display image in window"""
    cv2.imshow(title, image)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


def get_image_files(directory, extensions=['.jpg', '.jpeg', '.png', '.bmp']):
    """Get all image files from directory"""
    image_files = []
    for ext in extensions:
        image_files.extend(Path(directory).glob(f'*{ext}'))
        image_files.extend(Path(directory).glob(f'*{ext.upper()}'))
    return sorted(image_files)


def normalize_image(image):
    """Normalize image to [0, 1] range"""
    return image.astype('float32') / 255.0


def standardize_image(image):
    """Standardize image (mean=0, std=1)"""
    return (image - image.mean()) / (image.std() + 1e-7)


def convert_to_grayscale(image):
    """Convert BGR image to grayscale"""
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def apply_gaussian_blur(image, kernel_size=config.BLUR_KERNEL):
    """Apply Gaussian blur"""
    return cv2.GaussianBlur(image, kernel_size, 0)


def apply_binary_threshold(image, threshold=config.THRESHOLD_VALUE):
    """Apply binary thresholding"""
    _, binary = cv2.threshold(image, threshold, 255, cv2.THRESH_BINARY)
    return binary


def apply_morphological_operations(image, kernel_size=config.MORPH_KERNEL_SIZE):
    """Apply morphological operations (opening)"""
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, kernel_size)
    return cv2.morphologyEx(image, cv2.MORPH_OPEN, kernel)


def get_contours(image):
    """Get contours from binary image"""
    contours, _ = cv2.findContours(image, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    return contours


def draw_contour_rectangle(image, contours, color=(0, 255, 0), thickness=2):
    """Draw bounding rectangles around contours"""
    image_copy = image.copy()
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        cv2.rectangle(image_copy, (x, y), (x + w, y + h), color, thickness)
    return image_copy


def crop_region(image, x, y, w, h):
    """Crop a region from image"""
    return image[y:y+h, x:x+w]


def calculate_aspect_ratio(width, height):
    """Calculate aspect ratio"""
    return width / float(height) if height > 0 else 0


def is_valid_plate_region(x, y, w, h, min_area=config.MIN_CONTOUR_AREA, 
                         max_area=config.MAX_CONTOUR_AREA):
    """Check if region could be a license plate"""
    area = w * h
    aspect_ratio = calculate_aspect_ratio(w, h)
    
    # License plates can be horizontal (2.5-6.0), square (0.5-2.5), or vertical (0.15-0.5)
    valid_aspect = 0.5 <= aspect_ratio <= 6.0
    valid_area = min_area <= area <= max_area
    
    return valid_aspect and valid_area


def log_message(message, level='INFO'):
    """Log message with timestamp"""
    from datetime import datetime
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] [{level}] {message}")
