"""
Image preprocessing module for license plate recognition
"""
import cv2
import numpy as np
from src import utils
import config


class ImagePreprocessor:
    """Handle image preprocessing operations"""
    
    def __init__(self):
        self.blur_kernel = config.BLUR_KERNEL
        self.threshold_value = config.THRESHOLD_VALUE
        self.morph_kernel = config.MORPH_KERNEL_SIZE
    
    def preprocess(self, image, denoise=True, enhance=True):
        """
        Full preprocessing pipeline
        Args:
            image: Input image (BGR)
            denoise: Apply denoising
            enhance: Apply histogram equalization
        Returns:
            Preprocessed image
        """
        # Convert to grayscale
        gray = utils.convert_to_grayscale(image)
        
        # Denoise if requested
        if denoise:
            gray = cv2.fastNlMeansDenoising(gray, h=10)
        
        # Apply Gaussian blur
        blurred = utils.apply_gaussian_blur(gray, self.blur_kernel)
        
        # Apply thresholding
        binary = utils.apply_binary_threshold(blurred, self.threshold_value)
        
        # Apply morphological operations
        processed = utils.apply_morphological_operations(binary, self.morph_kernel)
        
        # Enhance contrast if requested
        if enhance:
            processed = self.enhance_contrast(processed)
        
        return processed
    
    def enhance_contrast(self, image):
        """Enhance contrast using CLAHE"""
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return clahe.apply(image)
    
    def adaptive_thresholding(self, gray_image):
        """Apply adaptive thresholding"""
        return cv2.adaptiveThreshold(
            gray_image, 255, 
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
            cv2.THRESH_BINARY, 11, 2
        )
    
    def deskew(self, image):
        """Correct skewed image"""
        coords = np.column_stack(np.where(image > 0))
        angle = cv2.minAreaRect(coords)[2]
        
        if angle < -45:
            angle = 90 + angle
        
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(image, M, (w, h), borderValue=255)
        
        return rotated
    
    def normalize_brightness(self, image):
        """Normalize brightness"""
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        
        normalized = cv2.merge([l, a, b])
        return cv2.cvtColor(normalized, cv2.COLOR_LAB2BGR)
    
    def remove_noise(self, binary_image):
        """Remove noise from binary image"""
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        cleaned = cv2.morphologyEx(binary_image, cv2.MORPH_OPEN, kernel)
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel)
        return cleaned


class PlateExtractor:
    """Extract license plate region from vehicle image"""
    
    def __init__(self):
        self.preprocessor = ImagePreprocessor()
        self.min_area = config.MIN_CONTOUR_AREA
        self.max_area = config.MAX_CONTOUR_AREA
    
    def detect_plate_regions(self, image):
        """
        Detect potential license plate regions
        Args:
            image: Input image (BGR)
        Returns:
            List of (x, y, w, h) tuples
        """
        # Preprocess image
        processed = self.preprocessor.preprocess(image)
        
        # Get contours
        contours = utils.get_contours(processed)
        
        # Filter valid plate regions
        valid_regions = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            
            if utils.is_valid_plate_region(x, y, w, h, self.min_area, self.max_area):
                valid_regions.append((x, y, w, h))
        
        # Sort by y-coordinate (assuming plate is in lower part of image)
        valid_regions.sort(key=lambda r: r[1], reverse=True)
        
        return valid_regions
    
    def extract_plate(self, image, x, y, w, h, padding=10):
        """
        Extract plate region with padding
        Args:
            image: Input image
            x, y, w, h: Bounding box
            padding: Padding around the plate
        Returns:
            Extracted plate image
        """
        h_img, w_img = image.shape[:2]
        
        x1 = max(0, x - padding)
        y1 = max(0, y - padding)
        x2 = min(w_img, x + w + padding)
        y2 = min(h_img, y + h + padding)
        
        return image[y1:y2, x1:x2]
    
    def extract_all_plates(self, image, padding=10):
        """Extract all detected plates"""
        regions = self.detect_plate_regions(image)
        plates = []
        
        for x, y, w, h in regions:
            plate = self.extract_plate(image, x, y, w, h, padding)
            plates.append({
                'image': plate,
                'bbox': (x, y, w, h),
                'x': x, 'y': y, 'w': w, 'h': h
            })
        
        return plates


class CharacterSegmentation:
    """Segment individual characters from license plate"""
    
    def segment_characters(self, plate_image, min_width=5, max_width=50):
        """
        Segment individual characters from plate
        Args:
            plate_image: Preprocessed plate image
            min_width, max_width: Character width constraints
        Returns:
            List of character images
        """
        contours = utils.get_contours(plate_image)
        
        characters = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            
            # Filter by width
            if min_width <= w <= max_width:
                char_img = utils.crop_region(plate_image, x, y, w, h)
                characters.append({
                    'image': char_img,
                    'x': x,
                    'bbox': (x, y, w, h)
                })
        
        # Sort by x-coordinate (left to right)
        characters.sort(key=lambda c: c['x'])
        
        return characters
    
    def resize_character(self, char_image, width=config.IMG_WIDTH, height=config.IMG_HEIGHT):
        """Resize character image to standard size"""
        return cv2.resize(char_image, (width, height))
