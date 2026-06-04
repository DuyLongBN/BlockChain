"""
Vietnamese License Plate OCR Module
Chuẩn OCR cho biển số xe Việt Nam

Vietnamese License Plate Format:
- Old format: XX.AB.123 (2 letters, 2 letters, 3 numbers)
- New format: XX - YY.ZZ (Province code - Issue sequence . Series)
- Example: 29A - 123.45

Province codes (first 2 characters):
- Letters: A-Z (excluding I, O, Q to avoid confusion)
- Used for representing 63 provinces/cities in Vietnam
"""

import cv2
import numpy as np
import re
from typing import Any, Dict, Tuple, List, Optional
import config

# Lazy import easyocr
easyocr = None
EASYOCR_AVAILABLE = None


# Vietnamese province codes (official 63 provinces)
VIETNAM_PROVINCE_CODES = {
    '01': 'Hà Nội', '02': 'Hồ Chí Minh', '03': 'Hải Phòng',
    '04': 'Đà Nẵng', '05': 'Cần Thơ', '06': 'Hà Giang',
    '07': 'Cao Bằng', '08': 'Bắc Kạn', '09': 'Tuyên Quang',
    '10': 'Lâm Đồng', '11': 'Điện Biên', '12': 'Lai Châu',
    '13': 'Sơn La', '14': 'Ý Yên', '15': 'Thanh Hóa',
    '16': 'Nghệ An', '17': 'Hà Tĩnh', '18': 'Quảng Bình',
    '19': 'Quảng Trị', '20': 'Thừa Thiên Huế', '21': 'Quảng Nam',
    '22': 'Quảng Ngãi', '23': 'Bình Định', '24': 'Phú Yên',
    '25': 'Khánh Hòa', '26': 'Ninh Thuận', '27': 'Bình Thuận',
    '28': 'Đồng Nai', '29': 'Bà Rịa Vũng Tàu', '30': 'Đồng Tháp',
    '31': 'An Giang', '32': 'Kiên Giang', '33': 'Cần Thơ (City)',
    '34': 'Tiền Giang', '35': 'Long An', '36': 'Bến Tre',
    '37': 'Vĩnh Long', '38': 'Trà Vinh', '39': 'Sóc Trăng',
    '40': 'Bạc Liêu', '41': 'Cà Mau', '42': 'Hưng Yên',
    '43': 'Hà Nam', '44': 'Nam Định', '45': 'Ninh Bình',
    '46': 'Vĩnh Phúc', '47': 'Bắc Giang', '48': 'Bắc Ninh',
    '49': 'Hải Dương', '50': 'Thái Nguyên', '51': 'Phú Thọ',
    '52': 'Hòa Bình', '53': 'Hà Giang (2)', '54': 'Cao Bằng (2)',
    '55': 'Bắc Kạn (2)', '56': 'Tuyên Quang (2)', '57': 'Lâm Đồng (2)',
    '58': 'Điện Biên (2)', '59': 'Lai Châu (2)', '60': 'Sơn La (2)',
    '61': 'Yên Bái', '62': 'Thái Bình', '63': 'Quảng Ninh',
    # Single letter codes for some provinces (alternative format)
    'A': 'Hà Nội', 'B': 'Hồ Chí Minh', 'C': 'Hải Phòng',
    'D': 'Đà Nẵng', 'E': 'Cần Thơ'
}

# Characters allowed on Vietnamese plates (excluding I, O, Q)
VIETNAM_ALLOWED_CHARS = '0123456789ABCDEFGHJKLMNPRSTUVWXYZ'  # No I, O, Q


class VietnameseOCREngine:
    """
    Vietnamese-optimized OCR engine for license plate recognition
    Công cụ OCR tối ưu hóa cho nhận dạng biển số xe Việt Nam
    """

    def __init__(self, use_gpu: bool = False):
        """
        Initialize Vietnamese OCR engine

        Args:
            use_gpu: Whether to use GPU acceleration (if available)
        """
        # Initialize EasyOCR with Vietnamese language (lazy)
        self.reader = None
        self.gpu_mode = use_gpu
        self._initialized = False
    
    def _ensure_reader_initialized(self):
        """Lazy-initialize EasyOCR reader when first needed"""
        global easyocr, EASYOCR_AVAILABLE
        
        if self._initialized:
            return
        
        # First time - try to import easyocr
        if EASYOCR_AVAILABLE is None:
            try:
                import easyocr as easyocr_module
                easyocr = easyocr_module
                EASYOCR_AVAILABLE = True
            except ImportError:
                EASYOCR_AVAILABLE = False
        
        # Now try to initialize the reader if easyocr is available
        if EASYOCR_AVAILABLE and self.reader is None:
            try:
                self.reader = easyocr.Reader(['en'], gpu=self.gpu_mode)
                print(f"Vietnamese OCR: EasyOCR reader initialized")
            except Exception as e:
                print(f"Vietnamese OCR: Failed to initialize EasyOCR: {e}")
                self.reader = None
        
        self._initialized = True

    def preprocess_plate_image(self, plate_image: np.ndarray) -> np.ndarray:
        """
        Preprocess plate image for better OCR accuracy (light version)
        Args:
            plate_image: Input plate image (BGR)
        Returns:
            Preprocessed grayscale image
        """
        # Convert to grayscale
        if len(plate_image.shape) == 3:
            gray = cv2.cvtColor(plate_image, cv2.COLOR_BGR2GRAY)
        else:
            gray = plate_image

        # Enhance contrast with CLAHE
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        return enhanced

    def _prepare_ocr_variants(self, plate_image: np.ndarray) -> List[np.ndarray]:
        """
        Create multiple preprocessed variants for OCR
        Different preprocessing works better for different lighting/plate conditions
        """
        variants = []
        
        # Ensure minimum size for OCR (at least 200px wide)
        h, w = plate_image.shape[:2]
        if w < 200:
            scale = 200.0 / w
            plate_image = cv2.resize(plate_image, None, fx=scale, fy=scale, 
                                     interpolation=cv2.INTER_LINEAR)
        
        # Strategy 1: Original color image (EasyOCR handles color well)
        variants.append(plate_image.copy())
        
        # Strategy 2: Grayscale + CLAHE (good for low contrast)
        if len(plate_image.shape) == 3:
            gray = cv2.cvtColor(plate_image, cv2.COLOR_BGR2GRAY)
        else:
            gray = plate_image.copy()
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        variants.append(enhanced)
        
        # Strategy 3: Sharpened grayscale (good for blurry images)
        kernel = np.array([[0, -1, 0],
                          [-1, 5, -1],
                          [0, -1, 0]])
        sharpened = cv2.filter2D(enhanced, -1, kernel)
        variants.append(sharpened)
        
        return variants

    def extract_text_easyocr(self, plate_image: np.ndarray,
                            confidence_threshold: float = 0.2) -> Tuple[str, float]:
        """
        Extract text using multi-strategy OCR approach
        Tries multiple preprocessing strategies, picks best result

        Args:
            plate_image: Input plate image
            confidence_threshold: Minimum confidence

        Returns:
            Tuple of (recognized_text, average_confidence)
        """
        try:
            # Ensure reader is initialized (lazy load)
            self._ensure_reader_initialized()
            
            # Check if reader is available
            if self.reader is None:
                print("Warning: EasyOCR reader not available, returning empty result")
                return "", 0.0
                
            # Try multiple preprocessing variants
            variants = self._prepare_ocr_variants(plate_image)
            
            best_text = ""
            best_confidence = 0.0
            best_parts = []
            
            for variant in variants:
                text_parts = []
                confidences = []
                
                # Run OCR
                results = self.reader.readtext(variant, detail=1, 
                                               allowlist='0123456789ABCDEFGHJKLMNPRSTUVWXYZ-.')
                
                for bbox, text, confidence in results:
                    if confidence >= confidence_threshold:
                        cleaned = self._clean_ocr_text(text)
                        if cleaned:
                            text_parts.append(cleaned)
                            confidences.append(confidence)
                
                if confidences:
                    avg_conf = float(np.mean(confidences))
                    combined_text = ''.join(text_parts)
                    
                    # Prefer results with more characters and higher confidence
                    score = avg_conf * (1 + 0.1 * len(combined_text))
                    best_score = best_confidence * (1 + 0.1 * len(best_text))
                    
                    if score > best_score:
                        best_text = combined_text
                        best_confidence = avg_conf
                        best_parts = text_parts
            
            return best_text, best_confidence

        except Exception as e:
            print(f"Error in EasyOCR: {e}")
            return "", 0.0

    def _refine_with_shape_analysis(self, character_images: List[Dict], 
                                    text_parts: List[str]) -> List[str]:
        """
        Refine character recognition using shape analysis
        Distinguish between easily confused characters: G vs 6, 5 vs 6, A vs 4

        Args:
            character_images: List of character regions with metadata
            text_parts: Initial recognized text parts

        Returns:
            Refined text parts
        """
        refined = []
        
        for i, text in enumerate(text_parts):
            if text == 'G' and i < len(character_images):
                # Analyze shape to distinguish G from 6
                char_img = character_images[i].get('image')
                if char_img is not None and char_img.size > 0:
                    # Shape feature: G has curved top-right, 6 has curve at bottom
                    is_likely_g = self._is_letter_g(char_img)
                    if not is_likely_g:
                        refined.append('6')
                    else:
                        refined.append(text)
                else:
                    refined.append(text)
            elif text == '6' and i < len(character_images):
                # Double-check if 6 should be G or 5
                char_img = character_images[i].get('image')
                if char_img is not None and char_img.size > 0:
                    is_likely_g = self._is_letter_g(char_img)
                    if is_likely_g:
                        refined.append('G')
                    else:
                        # Check if it's actually a 5
                        is_likely_5 = self._is_number_5(char_img)
                        if is_likely_5:
                            refined.append('5')
                        else:
                            refined.append(text)
                else:
                    refined.append(text)
            elif text == '5' and i < len(character_images):
                # Double-check if 5 should be 6
                char_img = character_images[i].get('image')
                if char_img is not None and char_img.size > 0:
                    is_likely_5 = self._is_number_5(char_img)
                    if not is_likely_5:
                        refined.append('6')
                    else:
                        refined.append(text)
                else:
                    refined.append(text)
            elif text == 'A' and i < len(character_images):
                # Double-check if A should be 4
                char_img = character_images[i].get('image')
                if char_img is not None and char_img.size > 0:
                    is_likely_a = self._is_letter_a(char_img)
                    if not is_likely_a:
                        refined.append('4')
                    else:
                        refined.append(text)
                else:
                    refined.append(text)
            elif text == '4' and i < len(character_images):
                # Double-check if 4 should be A
                char_img = character_images[i].get('image')
                if char_img is not None and char_img.size > 0:
                    is_likely_a = self._is_letter_a(char_img)
                    if is_likely_a:
                        refined.append('A')
                    else:
                        refined.append(text)
                else:
                    refined.append(text)
            elif text == 'S' and i < len(character_images):
                # Double-check if S should be 5
                char_img = character_images[i].get('image')
                if char_img is not None and char_img.size > 0:
                    is_likely_s = self._is_letter_s(char_img)
                    if not is_likely_s:
                        refined.append('5')
                    else:
                        refined.append(text)
                else:
                    refined.append(text)
            elif text == '5' and i < len(character_images):
                # Double-check if 5 should be S
                char_img = character_images[i].get('image')
                if char_img is not None and char_img.size > 0:
                    is_likely_5 = self._is_letter_s(char_img)
                    if is_likely_5:
                        refined.append('S')
                    else:
                        refined.append(text)
                else:
                    refined.append(text)
            elif text == 'T' and i < len(character_images):
                # Double-check if T should be 1
                char_img = character_images[i].get('image')
                if char_img is not None and char_img.size > 0:
                    is_likely_t = self._is_letter_t(char_img)
                    if not is_likely_t:
                        refined.append('1')
                    else:
                        refined.append(text)
                else:
                    refined.append(text)
            elif text == '1' and i < len(character_images):
                # Double-check if 1 should be T
                char_img = character_images[i].get('image')
                if char_img is not None and char_img.size > 0:
                    is_likely_t = self._is_letter_t(char_img)
                    if is_likely_t:
                        refined.append('T')
                    else:
                        refined.append(text)
                else:
                    refined.append(text)
            else:
                refined.append(text)
        
        return refined

    def _is_letter_g(self, char_image: np.ndarray) -> bool:
        """
        Determine if character image is more likely 'G' or '6'
        Using shape analysis:
        - G: Has a horizontal line/bar extending from the right middle
        - 6: Rounded bottom, no middle bar

        Args:
            char_image: Binary character image

        Returns:
            True if likely G, False if likely 6
        """
        if char_image is None or char_image.size == 0:
            return True
        
        try:
            # Normalize image to fixed size for consistent analysis
            char_img = cv2.resize(char_image, (32, 32))
            char_img = cv2.normalize(char_img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
            
            # Use resized dimensions (32x32)
            h, w = 32, 32
            
            # Calculate center regions
            top_third = char_img[:h//3, :]
            middle_third = char_img[h//3:2*h//3, :]
            bottom_third = char_img[2*h//3:, :]
            
            # Feature 1: Right side activity (G has bar on right)
            right_half = char_img[:, w//2:]
            middle_right = middle_third[:, w//2:]
            
            right_pixels = np.count_nonzero(right_half)
            middle_right_pixels = np.count_nonzero(middle_right)
            
            total_pixels = np.count_nonzero(char_img)
            
            # Feature 2: Bottom curvature (6 has more pixels at bottom)
            bottom_pixels = np.count_nonzero(bottom_third)
            top_pixels = np.count_nonzero(top_third)
            
            # Feature 3: Horizontal lines in middle (G characteristic)
            middle_horizontal = np.sum(middle_third, axis=0)  # Project vertically
            horizontal_bars = np.count_nonzero(middle_horizontal > h//3)
            
            # Decision logic
            # G: More pixels in middle-right area, less emphasis on bottom
            # 6: More pixels at bottom, rounded appearance
            
            if total_pixels == 0:
                return True
            
            right_ratio = right_pixels / total_pixels
            bottom_ratio = bottom_pixels / total_pixels
            top_ratio = top_pixels / total_pixels
            middle_right_ratio = middle_right_pixels / total_pixels
            
            # G indicators
            g_score = 0
            if middle_right_ratio > 0.15:  # G has significant middle-right pixels
                g_score += 2
            if right_ratio > 0.35:  # G has substantial right side activity
                g_score += 1
            if bottom_ratio < 0.25:  # G doesn't emphasize bottom
                g_score += 1
            
            # 6 indicators
            six_score = 0
            if bottom_ratio > 0.30:  # 6 has emphasized bottom
                six_score += 2
            if bottom_ratio > top_ratio:  # 6 has more at bottom than top
                six_score += 1
            if right_ratio < 0.30:  # 6 has less right-side activity
                six_score += 1
            
            return g_score >= six_score
            
        except Exception as e:
            print(f"Error in shape analysis: {e}")
            return True  # Default to G if analysis fails

    def _is_number_5(self, char_image: np.ndarray) -> bool:
        """
        Determine if character image is more likely '5' or '6'
        Using shape analysis:
        - 5: Has flat top with downward tail, more rectangular
        - 6: Rounded at top and bottom, more circular

        Args:
            char_image: Binary character image

        Returns:
            True if likely 5, False if likely 6
        """
        if char_image is None or char_image.size == 0:
            return False
        
        try:
            # Normalize image to fixed size
            char_img = cv2.resize(char_image, (32, 32))
            char_img = cv2.normalize(char_img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
            
            h, w = 32, 32
            
            # Divide into regions
            top_third = char_img[:h//3, :]
            middle_third = char_img[h//3:2*h//3, :]
            bottom_third = char_img[2*h//3:, :]
            
            total_pixels = np.count_nonzero(char_img)
            if total_pixels == 0:
                return False
            
            # Feature 1: Top flatness (5 has flat top)
            top_pixels = np.count_nonzero(top_third)
            top_ratio = top_pixels / total_pixels
            
            # Feature 2: Bottom hook (5 has curved tail at bottom)
            bottom_pixels = np.count_nonzero(bottom_third)
            bottom_ratio = bottom_pixels / total_pixels
            
            # Feature 3: Left side (5 has more on left due to horizontal top line)
            left_half = char_img[:, :w//2]
            left_pixels = np.count_nonzero(left_half)
            left_ratio = left_pixels / total_pixels
            
            # Feature 4: Right side activity
            right_half = char_img[:, w//2:]
            right_pixels = np.count_nonzero(right_half)
            right_ratio = right_pixels / total_pixels
            
            # Feature 5: Symmetry (5 is less symmetric than 6)
            top_left = np.count_nonzero(char_img[:h//2, :w//2])
            top_right = np.count_nonzero(char_img[:h//2, w//2:])
            bottom_left = np.count_nonzero(char_img[h//2:, :w//2])
            bottom_right = np.count_nonzero(char_img[h//2:, w//2:])
            
            symmetry = abs(top_left - top_right) + abs(bottom_left - bottom_right)
            
            # Decision logic
            # 5: More asymmetric, flat top, hook at bottom
            # 6: More symmetric, rounded top and bottom
            
            five_score = 0
            if top_ratio > 0.20:  # 5 has prominent top (flat line)
                five_score += 2
            if left_ratio > 0.52:  # 5 has more on left side
                five_score += 1
            if bottom_ratio < 0.25:  # 5 has less at bottom
                five_score += 1
            if symmetry > 10:  # 5 is less symmetric
                five_score += 1
            
            six_score = 0
            if top_ratio < 0.18:  # 6 has less prominent top
                six_score += 1
            if left_ratio < 0.50:  # 6 is more centered
                six_score += 1
            if bottom_ratio > 0.22:  # 6 has more at bottom
                six_score += 1
            if symmetry < 8:  # 6 is more symmetric
                six_score += 2
            
            return five_score >= six_score
            
        except Exception as e:
            print(f"Error in 5/6 shape analysis: {e}")
            return False  # Default to 6 if analysis fails

    def _is_letter_a(self, char_image: np.ndarray) -> bool:
        """
        Determine if character image is more likely 'A' or '4'
        Using shape analysis:
        - A: Has a pointed top, horizontal bar in middle
        - 4: Has more open top, closed bottom

        Args:
            char_image: Binary character image

        Returns:
            True if likely A, False if likely 4
        """
        if char_image is None or char_image.size == 0:
            return True
        
        try:
            # Normalize image to fixed size
            char_img = cv2.resize(char_image, (32, 32))
            char_img = cv2.normalize(char_img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
            
            h, w = 32, 32
            
            # Divide into regions
            top_third = char_img[:h//3, :]
            middle_third = char_img[h//3:2*h//3, :]
            bottom_third = char_img[2*h//3:, :]
            
            total_pixels = np.count_nonzero(char_img)
            if total_pixels == 0:
                return True
            
            # Feature 1: Top center concentration (A has pointed top)
            center_col = w//2
            top_center = np.count_nonzero(top_third[:, max(0, center_col-3):min(w, center_col+4)])
            top_center_ratio = top_center / max(1, np.count_nonzero(top_third))
            
            # Feature 2: Bottom bar (A has crossbar in middle)
            middle_pixels = np.count_nonzero(middle_third)
            middle_ratio = middle_pixels / total_pixels
            
            # Feature 3: Left/Right legs (A has two legs)
            left_pixels = np.count_nonzero(char_img[:, :w//3])
            right_pixels = np.count_nonzero(char_img[:, 2*w//3:])
            legs_symmetric = abs(left_pixels - right_pixels)
            
            # Feature 4: Bottom closure (4 is closed at bottom, A is open)
            bottom_pixels = np.count_nonzero(bottom_third)
            bottom_ratio = bottom_pixels / total_pixels
            
            # Decision logic
            # A: Pointed top, symmetric legs, horizontal crossbar
            # 4: Open top, more pixels at bottom
            
            a_score = 0
            if top_center_ratio > 0.50:  # A has concentrated top center
                a_score += 2
            if middle_ratio > 0.18:  # A has visible crossbar
                a_score += 1
            if legs_symmetric < 5:  # A legs are symmetric
                a_score += 1
            if bottom_ratio < 0.22:  # A is open at bottom
                a_score += 1
            
            four_score = 0
            if top_center_ratio < 0.40:  # 4 top is more dispersed
                four_score += 1
            if middle_ratio < 0.15:  # 4 has less crossbar
                four_score += 1
            if legs_symmetric > 8:  # 4 is less symmetric
                four_score += 1
            if bottom_ratio > 0.25:  # 4 is closed at bottom
                four_score += 2
            
            return a_score >= four_score
            
        except Exception as e:
            print(f"Error in A/4 shape analysis: {e}")
            return True  # Default to A if analysis fails

    def _is_letter_s(self, char_image: np.ndarray) -> bool:
        """
        Determine if character image is more likely 'S' or '5'
        Using shape analysis:
        - S: Has two curved bumps (top and bottom), smoother curves
        - 5: Has angular top, curved bottom only

        Args:
            char_image: Binary character image

        Returns:
            True if likely S, False if likely 5
        """
        if char_image is None or char_image.size == 0:
            return True
        
        try:
            char_img = cv2.resize(char_image, (32, 32))
            char_img = cv2.normalize(char_img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
            
            h, w = 32, 32
            
            # Divide into thirds
            top_third = char_img[:h//3, :]
            middle_third = char_img[h//3:2*h//3, :]
            bottom_third = char_img[2*h//3:, :]
            
            total_pixels = np.count_nonzero(char_img)
            if total_pixels == 0:
                return True
            
            # Feature 1: Top bump (S has curved top, 5 has more angular)
            top_pixels = np.count_nonzero(top_third)
            top_ratio = top_pixels / total_pixels
            
            # Feature 2: Middle width (S middle is narrower, 5 is wider)
            middle_pixels = np.count_nonzero(middle_third)
            middle_ratio = middle_pixels / total_pixels
            
            # Feature 3: Left vs Right distribution
            left_pixels = np.count_nonzero(char_img[:, :w//3])
            right_pixels = np.count_nonzero(char_img[:, 2*w//3:])
            
            # Feature 4: Bottom bump (both S and 5 have bottom)
            bottom_pixels = np.count_nonzero(bottom_third)
            bottom_ratio = bottom_pixels / total_pixels
            
            # S: Top bump ~20-25%, Middle ~30-35%, Balanced left-right
            # 5: Top bump ~15-20%, Top-heavy, Right-heavy
            
            s_score = 0
            if 0.18 < top_ratio < 0.30:  # S has moderate top
                s_score += 2
            if 0.28 < middle_ratio < 0.40:  # S middle is visible
                s_score += 1
            if abs(left_pixels - right_pixels) < 5:  # S is more balanced
                s_score += 1
            
            five_score = 0
            if top_ratio > 0.25:  # 5 has strong top
                five_score += 2
            if middle_ratio < 0.28:  # 5 middle is less visible
                five_score += 1
            if right_pixels > left_pixels + 3:  # 5 is right-heavy
                five_score += 1
            
            return s_score >= five_score
            
        except Exception as e:
            print(f"Error in S/5 shape analysis: {e}")
            return True  # Default to S

    def _is_letter_t(self, char_image: np.ndarray) -> bool:
        """
        Determine if character image is more likely 'T' or '1'
        Using shape analysis:
        - T: Has a horizontal top bar, stem below
        - 1: Thin vertical line, sometimes with serif at bottom

        Args:
            char_image: Binary character image

        Returns:
            True if likely T, False if likely 1
        """
        if char_image is None or char_image.size == 0:
            return True
        
        try:
            char_img = cv2.resize(char_image, (32, 32))
            char_img = cv2.normalize(char_img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
            
            h, w = 32, 32
            
            # Divide into thirds
            top_third = char_img[:h//3, :]
            middle_third = char_img[h//3:2*h//3, :]
            bottom_third = char_img[2*h//3:, :]
            
            total_pixels = np.count_nonzero(char_img)
            if total_pixels == 0:
                return True
            
            # Feature 1: Top width (T has wide top bar, 1 is narrow)
            top_width = 0
            for row in top_third:
                row_pixels = np.count_nonzero(row)
                top_width = max(top_width, row_pixels)
            top_width_ratio = top_width / w if w > 0 else 0
            
            # Feature 2: Width consistency (T stays wide, 1 gets narrow)
            middle_width = 0
            for row in middle_third:
                row_pixels = np.count_nonzero(row)
                middle_width = max(middle_width, row_pixels)
            middle_width_ratio = middle_width / w if w > 0 else 0
            
            # Feature 3: Pixels in top (T has many, 1 has few)
            top_pixels = np.count_nonzero(top_third)
            top_ratio = top_pixels / total_pixels
            
            # Feature 4: Total width average
            avg_width = 0
            for row in char_img:
                row_pixels = np.count_nonzero(row)
                avg_width += row_pixels
            avg_width = (avg_width / h) if h > 0 else 0
            avg_width_ratio = avg_width / w if w > 0 else 0
            
            # T: Wide top (>0.5), stays relatively wide (>0.35), has top pixels (>0.18)
            # 1: Narrow (avg <0.3), thin throughout
            
            t_score = 0
            if top_width_ratio > 0.50:  # T has wide top bar
                t_score += 2
            if middle_width_ratio > 0.35 and top_width_ratio > 0.45:  # T middle stays wide
                t_score += 1
            if top_ratio > 0.18:  # T has significant top
                t_score += 1
            
            one_score = 0
            if avg_width_ratio < 0.35:  # 1 is thin
                one_score += 2
            if top_width_ratio < 0.55:  # 1 top is not prominently wide
                one_score += 1
            if middle_width_ratio < 0.30:  # 1 middle is narrow
                one_score += 1
            
            return t_score >= one_score
            
        except Exception as e:
            print(f"Error in T/1 shape analysis: {e}")
            return True  # Default to T

    def _clean_ocr_text(self, text: str) -> str:
        """
        Clean OCR output text
        - Remove unwanted characters
        - Normalize Vietnamese characters
        - Keep only allowed characters for license plates
        - Intelligently correct common OCR misrecognitions

        Vietnamese plate structure: [2 digits province][1 letter series][numbers]
        Example: 12B116888 → province=12, series=B, id=116888

        Args:
            text: Raw OCR text

        Returns:
            Cleaned text
        """
        # Remove spaces and special characters but KEEP dashes and dots
        text = text.upper().strip()
        text = re.sub(r'[^A-Z0-9\-\.]', '', text)

        if not text:
            return text

        # Determine structure: find where the series letter is
        # Vietnamese plates: first 2 chars are province digits, 
        # 3rd char is series letter (A-Z), rest are ID numbers
        # Example: 12B116888, 29A12345, 30G49356
        
        # Find the position of the series letters (first alpha after leading digits, can be 1 or 2 letters)
        series_pos_start = -1
        series_pos_end = -1
        for i, ch in enumerate(text):
            if i >= 1 and ch.isalpha():
                if series_pos_start == -1:
                    series_pos_start = i
                series_pos_end = i
            elif series_pos_start != -1 and not ch.isalpha():
                break

        result = []
        for i, char in enumerate(text):
            is_series_letter = (series_pos_start <= i <= series_pos_end)
            is_province_area = (i < series_pos_start) if series_pos_start >= 0 else (i < 2)
            is_number_area = (series_pos_end >= 0 and i > series_pos_end)
            
            if is_series_letter:
                # This is the series letter — keep as letter, don't convert to number
                # Common OCR confusions at series position:
                if char == '8':
                    result.append('B')  # 8 → B at series position
                elif char == '6':
                    result.append('G')  # 6 → G at series position  
                elif char == '0':
                    result.append('D')  # 0 → D at series position
                elif char == '5':
                    result.append('S')  # 5 → S at series position (5 is not valid series letter)
                else:
                    result.append(char)
            elif is_number_area:
                # In number area — convert letters to likely numbers
                # But keep valid letters: S, T are valid on Vietnamese plates
                if char == 'Z':
                    result.append('2')
                elif char == 'I':
                    result.append('1')
                elif char == 'O':
                    result.append('0')
                elif char == 'B':
                    result.append('8')
                elif char == 'G':
                    result.append('6')
                elif char == 'S' or char == 'T':
                    # Keep S and T as valid letters (don't convert to numbers)
                    result.append(char)
                elif char.isalpha():
                    # Other letters in number area — try to keep if valid
                    result.append(char)
                else:
                    result.append(char)
            elif is_province_area:
                # Province code — should be digits
                if char == 'O':
                    result.append('0')
                elif char == 'I':
                    result.append('1')
                elif char == 'Z':
                    result.append('2')
                elif char == 'B':
                    result.append('8')
                elif char == 'S':
                    # Keep S as valid (don't convert to 5)
                    result.append(char)
                else:
                    result.append(char)
            else:
                result.append(char)
        
        text = ''.join(result)
        return text

    def format_vietnamese_plate(self, ocr_text: str) -> Optional[str]:
        """
        Format and validate Vietnamese license plate
        Supports multiple formats: 
        - 4-seater: XX-YYY.ZZ (e.g., 30G - 493.56)
        - Motorcycle 4-digit: XXXX (e.g., 1234 or XX-YY)
        - Old format: XX.AB.123

        Args:
            ocr_text: Raw OCR text

        Returns:
            Formatted plate string or None if invalid
        """
        text = ocr_text.upper().strip()
        text_clean = re.sub(r'[^A-Z0-9]', '', text)  # Pure alphanumeric for matching
        text = re.sub(r'[^A-Z0-9\-\.]', '', text)

        # Remove multiple consecutive dots or dashes
        text = re.sub(r'-+', '-', text)
        text = re.sub(r'\.+', '.', text)

        # ★ MOTORCYCLE 4-DIGIT FORMAT: Just 4 digits like "1234"
        # Vietnamese motorcycles sometimes have pure numeric plates
        if len(text_clean) == 4 and text_clean.isdigit():
            return text_clean  # Return as-is: "1234"
        
        # ★ MOTORCYCLE FORMAT: XX-YY or XX.YY (2 letters/digits + 2 digits)
        motorcycle_pattern = r'^([A-Z0-9]{2})\s*[\-\.]\s*(\d{2})$'
        match = re.match(motorcycle_pattern, text)
        if match:
            prefix = match.group(1)
            digits = match.group(2)
            return f"{prefix}-{digits}"

        # Try to match proper 1-row horizontal plates
        # Prefix is usually 2 digits + 1-2 letters/digits (e.g., "30G", "29A1", "51LD")
        # Total prefix length: 3 to 5 chars before the dash
        new_format_pattern = r'^([A-Z0-9]{3,5})\s*-\s*(\d{2,3})\.(\d{2,3})$'
        match = re.match(new_format_pattern, text)
        if match:
            prefix = match.group(1)
            row2_p1 = match.group(2)
            row2_p2 = match.group(3)
            return f"{prefix} - {row2_p1}.{row2_p2}"

        # Try to match old format: XX.AB.123
        old_format_pattern = r'^([A-Z0-9]{2,3})\.([A-Z0-9]{2,3})\.(\d{2,3})$'
        match = re.match(old_format_pattern, text)
        if match:
            return text

        # Try flexible matching with more lenient patterns for horizontal plates
        flexible_pattern = r'^([A-Z0-9]{3,5})\s*[\.\-]\s*(\d{2,3})\s*[\.\-]\s*(\d{2,3})$'
        match = re.match(flexible_pattern, text)
        if match:
            prefix = match.group(1)
            row2_p1 = match.group(2)
            row2_p2 = match.group(3)
            return f"{prefix} - {row2_p1}.{row2_p2}"

        # ★ Match concatenated 2-row plates: "12B116888" → "12B1 - 168.88"
        # Vietnamese 2-row plate structure:
        #   Row 1: [province 2 digits][series letter][0-2 digits]
        #   Row 2: [3 digits].[2 digits]  (5 digits total)
        # So concatenated: DD + L + D? + DDDDD
        # Examples: 12B1-16888, 29A1-23456, 30G-49356
        # Strategy: Take last 5 digits as row2, rest before is row1
        if len(text_clean) >= 7:
            # Find the series letter positions (could be 1 or 2 letters, e.g., 'G' or 'AA')
            letter_pos_start = -1
            letter_pos_end = -1
            
            for i, ch in enumerate(text_clean):
                if i >= 1 and ch.isalpha():
                    if letter_pos_start == -1:
                        letter_pos_start = i
                    letter_pos_end = i
                elif letter_pos_start != -1 and not ch.isalpha():
                    # Stop if we found digits after letters
                    break
            
            if letter_pos_start >= 1:
                # Everything after the last series letter is digits
                after_letter = text_clean[letter_pos_end + 1:]
                
                if after_letter.isdigit() and len(after_letter) >= 4:
                    # Row 2 is always last 5 digits (NNN.NN), or last 4-5 if shorter
                    prefix_part = text_clean[:letter_pos_end + 1]  # e.g. "12B" or "86AA"
                    
                    if len(after_letter) >= 6:
                        # e.g. "116888" → row1_extra="1", row2="16888"
                        row1_extra = after_letter[:len(after_letter) - 5]
                        row2 = after_letter[len(after_letter) - 5:]
                        plate_prefix = f"{prefix_part}{row1_extra}"
                        row2_formatted = f"{row2[:3]}.{row2[3:]}"
                        return f"{plate_prefix} - {row2_formatted}"
                    elif len(after_letter) == 5:
                        # e.g. "49356" → no row1_extra, row2="49356" 
                        row2_formatted = f"{after_letter[:3]}.{after_letter[3:]}"
                        return f"{prefix_part} - {row2_formatted}"
                    elif len(after_letter) >= 4:
                        # Shorter: "2345" → row2="2345"
                        row1_extra = after_letter[:1]
                        row2 = after_letter[1:]
                        plate_prefix = f"{prefix_part}{row1_extra}"
                        return f"{plate_prefix} - {row2}"

        # Partial recognition - at least 4 characters that look like a plate
        # This handles incomplete detections like "30G493" → "30G - 493"
        if len(text_clean) >= 4:
            # Try to extract province + series letter + numbers
            partial_pattern = r'^(\d{2}[A-Z]\d?)(.+)$'
            match = re.search(partial_pattern, text_clean)
            if match:
                prefix = match.group(1)
                rest = match.group(2)
                if len(rest) >= 2:
                    return f"{prefix} - {rest}"

        return None

    def validate_plate_format(self, plate_text: str) -> Dict[str, Any]:
        """
        Validate Vietnamese license plate format
        - Kiểm tra tính hợp lệ của định dạng biển số

        Args:
            plate_text: Plate text to validate

        Returns:
            Dictionary with validation results
        """
        result = {
            'valid': False,
            'text': plate_text,
            'province': None,
            'issue_code': None,
            'series': None,
            'errors': []
        }

        if not plate_text:
            result['errors'].append('Empty plate text')
            return result

        text = plate_text.upper().strip()

        # Check new format: 30G - 493.56
        new_format = r'^([A-Z0-9]{3,5})\s*-\s*(\d{2,3})\.(\d{2,3})$'
        match = re.match(new_format, text)

        if match:
            prefix, issue, series = match.groups()
            result['province'] = prefix[:2]
            result['issue_code'] = prefix[2:]
            result['series'] = f"{issue}{series}"
            result['valid'] = True
            return result

        # Check old format: XX.AB.123
        old_format = r'^([A-Z]{2})\.([A-Z]{2})\.(\d{3})$'
        match = re.match(old_format, text)

        if match:
            result['province'] = match.group(1)
            result['issue_code'] = match.group(2)
            result['series'] = match.group(3)
            result['valid'] = True
            return result

        # Check concatenated 2-row format: "12B1 - 168.88" or "12B1 - 16888"
        concat_format = r'^(\d{2}[A-Z]\d{0,2})\s*-\s*(.+)$'
        match = re.match(concat_format, text)

        if match:
            prefix = match.group(1)
            rest = match.group(2).replace('.', '')
            result['province'] = prefix[:2]
            result['issue_code'] = prefix[2:]
            result['series'] = rest
            result['valid'] = True
            return result

        # Invalid format
        result['errors'].append('Invalid plate format')
        result['errors'].append('Expected format: XX - YY.ZZ or XX.AB.123')

        return result

    def recognize_and_format(self, plate_image: np.ndarray) -> Dict[str, Any]:
        """
        Complete OCR pipeline: recognize and format Vietnamese plate
        - Pipeline hoàn chỉnh: nhận dạng và định dạng biển số Việt Nam

        Args:
            plate_image: Input plate image (BGR)

        Returns:
            Dictionary with recognition results and validation
        """
        # Extract text using EasyOCR
        raw_text, confidence = self.extract_text_easyocr(plate_image)

        # Format the text
        formatted_text = self.format_vietnamese_plate(raw_text)

        # If formatting failed, use raw text as fallback
        if not formatted_text:
            formatted_text = raw_text

        # Validate format
        validation = self.validate_plate_format(formatted_text)

        result = {
            'raw_ocr': raw_text,
            'formatted_text': formatted_text,
            'confidence': float(confidence),
            'validation': validation,
            'success': validation.get('valid', False)
        }

        return result


class VietnameseCharacterSegmentation:
    """
    Character segmentation optimized for Vietnamese license plates
    Phân tách ký tự tối ưu hóa cho biển số Việt Nam
    """

    def __init__(self):
        """Initialize character segmentation"""
        pass

    def segment_characters(self, plate_image: np.ndarray) -> List[Dict]:
        """
        Segment individual characters from plate image
        - Phân tách từng ký tự từ hình ảnh biển số

        Args:
            plate_image: Preprocessed plate image

        Returns:
            List of dictionaries containing character images and positions
        """
        # Convert to grayscale if needed
        if len(plate_image.shape) == 3:
            gray = cv2.cvtColor(plate_image, cv2.COLOR_BGR2GRAY)
        else:
            gray = plate_image

        # Apply threshold
        _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)

        # Find contours
        contours, _ = cv2.findContours(binary, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        # Filter and sort contours by x-coordinate (left to right)
        characters = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)

            # Filter by size (reasonable character dimensions)
            if w > 3 and h > 8 and w < 100 and h < 150:
                char_data = {
                    'image': binary[y:y+h, x:x+w],
                    'bbox': (x, y, w, h),
                    'center_x': x + w // 2
                }
                characters.append(char_data)

        # Sort by x-coordinate
        characters.sort(key=lambda c: c['center_x'])

        return characters

    def get_character_roi(self, plate_image: np.ndarray,
                         character_bbox: Tuple[int, int, int, int]) -> np.ndarray:
        """
        Extract Region of Interest (ROI) for a single character

        Args:
            plate_image: Source plate image
            character_bbox: Bounding box (x, y, w, h)

        Returns:
            Character ROI image
        """
        x, y, w, h = character_bbox
        return plate_image[y:y+h, x:x+w]
