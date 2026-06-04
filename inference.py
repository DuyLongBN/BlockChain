"""
Inference module for license plate recognition
Mô-đun suy diễn cho nhận dạng biển số xe
"""
import cv2
import numpy as np
import re
import threading
try:
    import tensorflow as tf
    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False
from pathlib import Path
import config
from src import utils, image_processing, vietnamese_ocr

# Lazy import easyocr - will be imported when needed
easyocr = None
EASYOCR_AVAILABLE = None  # Will be determined on first use


class LicensePlateRecognizer:
    """End-to-end license plate recognition system
    Hệ thống nhận dạng biển số xe hoàn chỉnh
    """
    
    def __init__(self, model_path=None, use_vietnamese_ocr=True, use_yolo=True):
        """
        Initialize recognizer
        Args:
            model_path: Path to trained model
            use_vietnamese_ocr: Whether to use Vietnamese OCR optimization
            use_yolo: Whether to use YOLO for plate detection
        """
        self.preprocessor = image_processing.ImagePreprocessor()
        self.plate_extractor = image_processing.PlateExtractor()
        self.char_segmentation = image_processing.CharacterSegmentation()
        
        # Initialize YOLO plate detector
        self.yolo_model = None
        self.detector_model_path = None
        self.detector_model_names = {}
        self.use_yolo = use_yolo
        if use_yolo:
            try:
                from ultralytics import YOLO
                yolo_path = self._find_plate_detector_path(model_path)

                if yolo_path:
                    candidate_model = YOLO(yolo_path)
                    if self._is_plate_detector(candidate_model):
                        self.yolo_model = candidate_model
                        self.detector_model_path = str(yolo_path)
                        self.detector_model_names = dict(getattr(candidate_model, 'names', {}) or {})
                        utils.log_message(f"YOLO plate model loaded from {yolo_path}", 'INFO')
                        self.use_yolo = True
                    else:
                        utils.log_message(
                            f"YOLO model at {yolo_path} is not a license-plate detector; using contour fallback",
                            'WARNING'
                        )
                        self.use_yolo = False
                else:
                    utils.log_message("YOLO model not found, falling back to contour detection", 'WARNING')
                    self.use_yolo = False
            except ImportError:
                utils.log_message("ultralytics not available, using contour detection", 'WARNING')
                self.use_yolo = False
            except Exception as e:
                utils.log_message(f"Error initializing YOLO: {e}", 'WARNING')
                self.use_yolo = False
        
        # Load trained model if provided and TensorFlow is available
        self.model = None
        if TF_AVAILABLE and model_path and Path(model_path).exists():
            try:
                self.model = tf.keras.models.load_model(model_path)
                utils.log_message(f"Loaded model from {model_path}")
            except Exception as e:
                utils.log_message(f"Failed to load model: {e}", 'WARNING')
                self.model = None
        else:
            if not TF_AVAILABLE:
                utils.log_message("TensorFlow not available, using EasyOCR for recognition", 'INFO')
            else:
                utils.log_message("No trained model provided, using EasyOCR instead")
        
        # Initialize Vietnamese OCR if enabled
        self.use_vietnamese_ocr = use_vietnamese_ocr and config.VIETNAM_OCR_ENABLED
        self.vietnam_ocr = None
        self.ocr = None
        self._ocr_lock = threading.Lock()
        
        if self.use_vietnamese_ocr:
            self.vietnam_ocr = vietnamese_ocr.VietnameseOCREngine(use_gpu=False)
            utils.log_message("Vietnamese OCR engine initialized")
        else:
            # Fallback to standard EasyOCR
            if EASYOCR_AVAILABLE:
                try:
                    self.ocr = easyocr.Reader(['en'], gpu=False)
                except Exception as e:
                    utils.log_message(f"Failed to initialize EasyOCR: {e}", 'WARNING')
                    self.ocr = None
            else:
                utils.log_message("EasyOCR not available, using Vietnamese OCR only", 'WARNING')
        
        self.char_to_idx = {char: idx for idx, char in enumerate(config.ALLOWED_CHARS)}
        self.idx_to_char = {idx: char for char, idx in self.char_to_idx.items()}

    @staticmethod
    def _find_plate_detector_path(model_path=None):
        if model_path and Path(model_path).exists():
            return str(model_path)

        candidates = [
            'models/best.pt',
            'runs/detect/train/weights/best.pt',
        ]
        for candidate in candidates:
            if Path(candidate).exists():
                return candidate
        return None

    @staticmethod
    def _is_plate_detector(yolo_model):
        names = getattr(yolo_model, 'names', {}) or {}
        label_text = ' '.join(str(v).lower() for v in names.values())
        return 'plate' in label_text or 'license' in label_text or 'licence' in label_text
    
    def recognize_plate(
        self,
        image_path,
        detection_confidence=0.3,
        yolo_imgsz=None,
        use_contour_fallback=True,
        use_full_frame_ocr_fallback=False,
        always_run_full_frame_ocr_fallback=False,
        max_plate_candidates=None,
        ocr_fast=False
    ):
        """
        Recognize license plate from image
        Args:
            image_path: Path to vehicle image
        Returns:
            Dictionary with detection and recognition results
        """
        # Load image
        image = utils.load_image(str(image_path))
        
        # Detect plate regions - use YOLO if available
        plates = []
        if self.use_yolo and self.yolo_model is not None:
            utils.log_message("Using YOLO for plate detection", 'DEBUG')
            try:
                yolo_kwargs = {'conf': detection_confidence, 'verbose': False}
                if yolo_imgsz:
                    yolo_kwargs['imgsz'] = yolo_imgsz
                results = self.yolo_model(image, **yolo_kwargs)
                for result in results:
                    if result.boxes is not None and len(result.boxes) > 0:
                        for box in result.boxes:
                            x1, y1, x2, y2 = map(int, box.xyxy[0])
                            # Add enough padding for OCR. Tight YOLO boxes often clip
                            # the first/last characters and make EasyOCR read 30G as 80G.
                            box_w = max(1, x2 - x1)
                            box_h = max(1, y2 - y1)
                            padding_x = max(14, int(box_w * 0.10))
                            padding_y = max(8, int(box_h * 0.12))
                            x1 = max(0, x1 - padding_x)
                            y1 = max(0, y1 - padding_y)
                            x2 = min(image.shape[1], x2 + padding_x)
                            y2 = min(image.shape[0], y2 + padding_y)
                            
                            plate_img = image[y1:y2, x1:x2]
                            if plate_img.size > 0:
                                width = x2 - x1
                                height = y2 - y1
                                plates.append({
                                    'image': plate_img,
                                    'bbox': (x1, y1, width, height),
                                    'x': x1, 'y': y1, 'w': width, 'h': height,
                                    'confidence': float(box.conf[0]) if box.conf is not None else 0.0
                                })
                utils.log_message(f"YOLO detected {len(plates)} plates", 'INFO')
            except Exception as e:
                utils.log_message(f"YOLO detection error: {e}, falling back to contour", 'WARNING')
                self.use_yolo = False
        
        if not plates and use_contour_fallback:
            utils.log_message("Using contour-based plate detection", 'DEBUG')
            plates = self.plate_extractor.extract_all_plates(image)
            utils.log_message(f"Contour detection found {len(plates)} plates", 'INFO')

        if max_plate_candidates and len(plates) > max_plate_candidates:
            image_area = max(1, image.shape[0] * image.shape[1])

            def plate_region_rank(plate):
                bbox = plate.get('bbox', (0, 0, 1, 1))
                width = max(1, int(plate.get('w', bbox[2])))
                height = max(1, int(plate.get('h', bbox[3])))
                aspect = width / height
                area_ratio = (width * height) / image_area
                aspect_score = 1.0 - min(abs(aspect - 2.6) / 2.6, 1.0)
                size_penalty = 0.4 if area_ratio > 0.22 else 0.0
                return float(plate.get('confidence', 0.0) or 0.0) + aspect_score - size_penalty

            plates = sorted(plates, key=plate_region_rank, reverse=True)[:max_plate_candidates]
        
        results = {
            'image_path': str(image_path),
            'plates': []
        }
        
        for plate_data in plates:
            plate_img = plate_data['image']
            plate_bbox = plate_data['bbox']
            plate_img, plate_bbox = self._tighten_plate_crop_repeated(plate_img, plate_bbox)
            
            # Try direct EasyOCR first - simplest and most reliable
            recognition = self._recognize_with_ocr(plate_img, fast=ocr_fast)
            
            # If EasyOCR fails or returns empty, fallback to neural network or Vietnamese OCR
            if not recognition.get('plate_number') or recognition.get('plate_number') == 'UNKNOWN':
                if self.model is not None:
                    recognition = self._recognize_with_model(plate_img)
                elif self.use_vietnamese_ocr:
                    recognition = self._recognize_with_vietnamese_ocr(plate_img)
            
            results['plates'].append({
                'bbox': plate_bbox,
                'recognition': recognition
            })

        if use_full_frame_ocr_fallback:
            has_plausible_plate = any(
                self._is_plausible_plate_number(
                    plate.get('recognition', {}).get('plate_number', '')
                )
                for plate in results['plates']
            )
            if always_run_full_frame_ocr_fallback or not has_plausible_plate:
                fallback_results = self._detect_plates_with_full_frame_ocr(image)
                if fallback_results:
                    results['plates'].extend(fallback_results)

        results['plates'] = self._dedupe_plate_results(results['plates'])
        
        return results

    def recognize_webcam_frame_fast(self, image):
        """Fast path for webcam frames: OCR only bright plate-like crops first."""
        phone_yolo_results = self._recognize_webcam_phone_yolo_regions(
            image,
            max_regions=1,
            fast=True
        )
        if phone_yolo_results:
            return {
                'image_path': 'webcam_frame',
                'plates': phone_yolo_results
            }

        phone_results = self._recognize_webcam_phone_plate_regions(
            image,
            max_regions=1,
            fast=True
        )
        if phone_results:
            return {
                'image_path': 'webcam_frame',
                'plates': phone_results
            }

        return {
            'image_path': 'webcam_frame',
            'plates': self._detect_plates_with_full_frame_ocr(
                image,
                max_bright_regions=1,
                allow_full_frame=False,
                square_extra=True,
                stop_after_first_candidate=True
            )
        }

    def recognize_webcam_frame_deep(self, image, detection_confidence=0.16, yolo_imgsz=768):
        """In-memory webcam recognition for frames where the bright-region scan misses."""
        recognized = self._recognize_webcam_phone_yolo_regions(
            image,
            max_regions=2,
            fast=True
        )
        recognized.extend(self._recognize_webcam_phone_plate_regions(
            image,
            max_regions=2,
            fast=True
        ))
        if any(
            self._is_plausible_plate_number(
                plate.get('recognition', {}).get('plate_number', '')
            )
            for plate in recognized
        ):
            return {
                'image_path': 'webcam_frame',
                'plates': self._dedupe_plate_results(recognized)
            }

        plates = []
        if self.use_yolo and self.yolo_model is not None:
            try:
                yolo_kwargs = {'conf': detection_confidence, 'verbose': False}
                if yolo_imgsz:
                    yolo_kwargs['imgsz'] = yolo_imgsz
                results = self.yolo_model(image, **yolo_kwargs)
                for result in results:
                    if result.boxes is None or len(result.boxes) == 0:
                        continue
                    for box in result.boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        box_w = max(1, x2 - x1)
                        box_h = max(1, y2 - y1)
                        padding_x = max(10, int(box_w * 0.08))
                        padding_y = max(6, int(box_h * 0.10))
                        x1 = max(0, x1 - padding_x)
                        y1 = max(0, y1 - padding_y)
                        x2 = min(image.shape[1], x2 + padding_x)
                        y2 = min(image.shape[0], y2 + padding_y)
                        plate_img = image[y1:y2, x1:x2]
                        if plate_img.size == 0:
                            continue
                        plates.append({
                            'image': plate_img,
                            'bbox': (x1, y1, x2 - x1, y2 - y1),
                            'confidence': float(box.conf[0]) if box.conf is not None else 0.0
                        })
            except Exception as e:
                utils.log_message(f"Webcam YOLO deep scan failed: {e}", 'DEBUG')

        recognized = []
        image_area = max(1, image.shape[0] * image.shape[1])
        for plate_data in sorted(
            plates,
            key=lambda item: float(item.get('confidence', 0.0) or 0.0),
            reverse=True
        )[:2]:
            x, y, w, h = plate_data['bbox']
            area_ratio = (w * h) / image_area
            if area_ratio > 0.35:
                continue
            plate_img = plate_data['image']
            plate_bbox = plate_data['bbox']
            plate_img, plate_bbox = self._tighten_plate_crop_repeated(plate_img, plate_bbox)
            recognition = self._recognize_with_ocr(plate_img, fast=True)
            recognized.append({
                'bbox': plate_bbox,
                'recognition': recognition
            })

        has_plausible_plate = any(
            self._is_plausible_plate_number(
                plate.get('recognition', {}).get('plate_number', '')
            )
            for plate in recognized
        )
        if not has_plausible_plate:
            recognized.extend(self._detect_plates_with_full_frame_ocr(
                image,
                max_bright_regions=2,
                allow_full_frame=False,
                square_extra=True,
                stop_after_first_candidate=True,
                max_ocr_strategies=2
            ))

        return {
            'image_path': 'webcam_frame',
            'plates': self._dedupe_plate_results(recognized)
        }
    
    def _recognize_with_model(self, plate_image):
        """Recognize plate using trained neural network"""
        try:
            # Preprocess
            processed = self.preprocessor.preprocess(plate_image)
            
            # Segment characters
            characters = self.char_segmentation.segment_characters(processed)
            
            plate_number = ""
            confidences = []
            
            for char_data in characters:
                char_img = char_data['image']
                
                # Resize to model input size
                resized = self.char_segmentation.resize_character(char_img)
                resized = utils.normalize_image(resized)
                
                # Predict
                predictions = self.model.predict(np.expand_dims(resized, 0), verbose=0)
                char_idx = np.argmax(predictions[0])
                confidence = predictions[0][char_idx]
                
                if confidence > config.RECOGNITION_CONFIDENCE:
                    char = self.idx_to_char.get(char_idx, '?')
                    plate_number += char
                    confidences.append(float(confidence))
            
            avg_confidence = np.mean(confidences) if confidences else 0
            
            return {
                'method': 'neural_network',
                'plate_number': plate_number,
                'confidence': avg_confidence
            }
        
        except Exception as e:
            utils.log_message(f"Error with neural network recognition: {e}", 'WARNING')
            if self.use_vietnamese_ocr:
                return self._recognize_with_vietnamese_ocr(plate_image)
            else:
                return self._recognize_with_ocr(plate_image)
    
    def _recognize_with_vietnamese_ocr(self, plate_image):
        """Recognize plate using Vietnamese-optimized OCR"""
        try:
            if self.vietnam_ocr is None:
                utils.log_message("Vietnamese OCR not initialized, falling back to EasyOCR", 'WARNING')
                return self._recognize_with_ocr(plate_image)
            
            # Use Vietnamese OCR engine
            result = self.vietnam_ocr.recognize_and_format(plate_image)
            
            return {
                'method': 'vietnamese_ocr',
                'plate_number': result.get('formatted_text', result.get('raw_ocr', '')),
                'raw_text': result.get('raw_ocr', ''),
                'confidence': result.get('confidence', 0.0),
                'validation': result.get('validation', {}),
                'is_valid': result.get('success', False)
            }
        
        except Exception as e:
            utils.log_message(f"Error with Vietnamese OCR: {e}", 'WARNING')
            return self._recognize_with_ocr(plate_image)
    
    def _recognize_with_ocr(self, plate_image, fast=False):
        """Recognize plate using EasyOCR (fallback)"""
        try:
            if not self._ensure_easyocr_reader():
                return {
                    'method': 'error',
                    'plate_number': 'UNKNOWN',
                    'confidence': 0.0,
                    'raw_text': ''
                }
            
            original_plate_image = plate_image.copy()
            allow_single_line_char_ocr = self._looks_like_single_line_plate_crop(original_plate_image)

            # Upscale small plate images (OCR works better on larger text)
            h, w = plate_image.shape[:2]
            if w < 360 or h < 120:
                scale = max(360 / w, 120 / h) if w > 0 and h > 0 else 2
                plate_image = cv2.resize(plate_image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                utils.log_message(f"Upscaled plate image by {scale:.1f}x", 'DEBUG')
            
            # Try multiple preprocessing strategies
            if fast:
                strategies = [
                    ("direct", plate_image),
                    ("clahe", self._preprocess_clahe(plate_image)),
                    ("otsu", self._preprocess_otsu(plate_image)),
                ]
            else:
                strategies = [
                    ("direct", plate_image),
                    ("grayscale", self._preprocess_grayscale(plate_image)),
                    ("clahe", self._preprocess_clahe(plate_image)),
                    ("sharpen", self._preprocess_sharpen(plate_image)),
                    ("otsu", self._preprocess_otsu(plate_image)),
                ]
            
            best_result = None
            best_score = 0
            ocr_candidates = []
            
            for strategy_name, processed_img in strategies:
                try:
                    # Ensure image is BGR for OCR
                    if len(processed_img.shape) == 2:
                        # Grayscale - convert to BGR for easyocr
                        processed_img = cv2.cvtColor(processed_img, cv2.COLOR_GRAY2BGR)
                    
                    if fast:
                        ocr_runs = [
                            ("plate_chars", self.ocr.readtext(
                                processed_img,
                                detail=1,
                                allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-. '
                            )),
                        ]
                    else:
                        ocr_runs = [
                            ("free", self.ocr.readtext(processed_img, detail=1)),
                            ("plate_chars", self.ocr.readtext(
                                processed_img,
                                detail=1,
                                allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-. '
                            )),
                        ]
                    
                    for ocr_mode, ocr_results in ocr_runs:
                        if not ocr_results:
                            continue

                        candidate = self._build_ocr_candidate(ocr_results)
                        if not candidate:
                            continue

                        plate_number = candidate['plate_number']
                        avg_confidence = candidate['confidence']
                        score = self._score_plate_candidate(plate_number, avg_confidence)
                        score += self._score_raw_series_support(plate_number, candidate['raw_text'])
                        ocr_candidates.append({
                            'method': 'easyocr',
                            'strategy': f"{strategy_name}_{ocr_mode}",
                            'plate_number': plate_number,
                            'confidence': float(avg_confidence),
                            'raw_text': candidate['raw_text'],
                            'score': score
                        })

                        if score > best_score:
                            best_score = score
                            best_result = {
                                'method': 'easyocr',
                                'strategy': f"{strategy_name}_{ocr_mode}",
                                'plate_number': plate_number,
                                'confidence': float(avg_confidence),
                                'raw_text': candidate['raw_text']
                            }

                        utils.log_message(f"OCR ({strategy_name}/{ocr_mode}): '{plate_number}' (conf={avg_confidence:.3f}, score={score:.2f})", 'DEBUG')
                
                except Exception as e:
                    utils.log_message(f"OCR strategy {strategy_name} failed: {e}", 'DEBUG')
                    continue
            
            if best_result:
                best_result = self._choose_consensus_ocr_result(ocr_candidates, best_result)
                if not fast and not allow_single_line_char_ocr:
                    best_result = self._correct_two_line_plate_top_with_ocr(best_result, original_plate_image)
                    best_result = self._correct_two_line_plate_with_char_ocr(best_result, original_plate_image)
                if not fast and allow_single_line_char_ocr:
                    char_result = self._recognize_single_line_with_char_ocr(original_plate_image)
                    if not char_result:
                        char_result = self._recognize_single_line_with_char_ocr(plate_image)
                    if char_result and (
                        not self._is_plausible_plate_number(best_result.get('plate_number', ''))
                        or float(char_result.get('confidence', 0.0) or 0.0) >= float(best_result.get('confidence', 0.0) or 0.0) - 0.12
                    ):
                        best_result = char_result
                if not self._is_plausible_plate_number(best_result.get('plate_number', '')):
                    utils.log_message(
                        f"Rejected OCR result that does not match Vietnamese plate format: "
                        f"'{best_result.get('plate_number', '')}'",
                        'WARNING'
                    )
                    return {
                        'method': 'error',
                        'strategy': best_result.get('strategy', 'ocr_rejected'),
                        'plate_number': 'UNKNOWN',
                        'confidence': 0.0,
                        'raw_text': best_result.get('raw_text', '')
                    }
                utils.log_message(f"Best OCR result: '{best_result['plate_number']}' ({best_result['strategy']}, conf={best_result['confidence']:.3f})", 'INFO')
                return best_result
            else:
                if not fast and allow_single_line_char_ocr:
                    char_result = self._recognize_single_line_with_char_ocr(original_plate_image)
                    if not char_result:
                        char_result = self._recognize_single_line_with_char_ocr(plate_image)
                    if char_result:
                        utils.log_message(f"Best OCR result: '{char_result['plate_number']}' ({char_result['strategy']}, conf={char_result['confidence']:.3f})", 'INFO')
                        return char_result
                utils.log_message("No valid OCR results from any strategy", 'WARNING')
                return {
                    'method': 'error',
                    'plate_number': 'UNKNOWN',
                    'confidence': 0.0,
                    'raw_text': ''
                }
        
        except Exception as e:
            utils.log_message(f"Error with OCR recognition: {e}", 'ERROR')
            import traceback
            traceback.print_exc()
            return {
                'method': 'error',
                'plate_number': 'UNKNOWN',
                'confidence': 0.0,
                'raw_text': ''
            }

    @staticmethod
    def _looks_like_single_line_plate_crop(plate_image):
        if plate_image is None:
            return False
        h, w = plate_image.shape[:2]
        if h <= 0:
            return False
        # Vietnamese two-line plates can still be wider than tall after YOLO
        # padding. Treat only clearly wide crops as one-line plates; otherwise
        # character OCR may read stacked rows left-to-right and produce a very
        # confident but wrong result.
        return (w / h) >= 2.35

    def _correct_two_line_plate_top_with_ocr(self, recognition, plate_image):
        """Cross-check the top row of square plates before trusting inferred series letters."""
        if not recognition or not self._is_plausible_plate_number(recognition.get('plate_number', '')):
            return recognition
        if plate_image is None or plate_image.size == 0 or self._looks_like_single_line_plate_crop(plate_image):
            return recognition
        if not self._ensure_easyocr_reader():
            return recognition

        current_top, bottom = self._split_plate_top_bottom(recognition.get('plate_number', ''))
        current_top = re.sub(r'[^A-Z0-9]', '', current_top)
        if len(current_top) not in {3, 4} or len(bottom) not in {4, 5} or not bottom.isdigit():
            return recognition
        current_raw = re.sub(r'[^A-Z0-9]', '', (recognition.get('raw_text', '') or '').upper())
        if len(current_raw) >= 3 and current_raw[2].isalpha():
            return recognition

        h, w = plate_image.shape[:2]
        top_crop = plate_image[:max(1, int(h * 0.58)), :]
        if top_crop.size == 0:
            return recognition

        scale = max(1.0, 420 / max(1, w))
        scale = min(scale, 6.0)
        enlarged = cv2.resize(top_crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        variants = [
            ("direct", enlarged),
            ("otsu", self._preprocess_otsu(enlarged)),
            ("adaptive", self._preprocess_adaptive(enlarged)),
        ]

        candidates = []
        for strategy_name, variant in variants:
            try:
                if len(variant.shape) == 2:
                    variant = cv2.cvtColor(variant, cv2.COLOR_GRAY2BGR)
                ocr_results = self.ocr.readtext(
                    variant,
                    detail=1,
                    allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-',
                    decoder='greedy',
                    batch_size=1,
                    workers=0,
                    canvas_size=512,
                    mag_ratio=1.0
                )
            except Exception as e:
                utils.log_message(f"Top-row OCR cross-check failed ({strategy_name}): {e}", 'DEBUG')
                continue

            if not ocr_results:
                continue

            ordered = sorted(
                ocr_results,
                key=lambda item: min(point[0] for point in item[0]) if item[0] else 0
            )
            raw_top = self._clean_plate_text(''.join(str(item[1]) for item in ordered))
            raw_top_compact = re.sub(r'[^A-Z0-9]', '', raw_top)
            if len(raw_top_compact) < 3 or not raw_top_compact[2].isalpha():
                continue
            normalized_top = re.sub(r'[^A-Z0-9]', '', self._normalize_plate_top_line(raw_top))
            if not self._is_plausible_two_line_top(normalized_top):
                continue

            confidences = [float(item[2] or 0.0) for item in ordered]
            candidates.append({
                'top': normalized_top,
                'confidence': float(np.mean(confidences)) if confidences else 0.0,
                'strategy': strategy_name,
                'raw_text': raw_top
            })

        if not candidates:
            return recognition

        groups = {}
        for candidate in candidates:
            groups.setdefault(candidate['top'], []).append(candidate)

        selected_top, selected_items = max(
            groups.items(),
            key=lambda item: (
                len(item[1]),
                max(candidate['confidence'] for candidate in item[1]),
                float(np.mean([candidate['confidence'] for candidate in item[1]]))
            )
        )
        best_support = max(selected_items, key=lambda item: item['confidence'])
        if selected_top == current_top:
            return recognition

        has_consensus = len(selected_items) >= 2 and best_support['confidence'] >= 0.40
        has_strong_read = best_support['confidence'] >= 0.78
        if not has_consensus and not has_strong_read:
            return recognition

        corrected_plate = self._apply_plate_series_corrections(f"{selected_top}-{bottom}")
        if not self._is_plausible_plate_number(corrected_plate):
            return recognition

        updated = dict(recognition)
        updated['plate_number'] = corrected_plate
        updated['strategy'] = f"{recognition.get('strategy', 'ocr')}_top_row_consensus"
        updated['raw_text'] = recognition.get('raw_text', '')
        updated['top_row_raw_text'] = best_support['raw_text']
        updated['confidence'] = max(
            float(recognition.get('confidence', 0.0) or 0.0),
            min(float(np.mean([item['confidence'] for item in selected_items])), 0.78)
        )
        return updated

    @staticmethod
    def _is_plausible_two_line_top(top):
        if len(top) not in {3, 4}:
            return False
        if not top[:2].isdigit() or not top[2].isalpha():
            return False
        return len(top) == 3 or top[3].isdigit()

    def _correct_two_line_plate_with_char_ocr(self, recognition, plate_image):
        if not recognition or not self._is_plausible_plate_number(recognition.get('plate_number', '')):
            return recognition
        if self._looks_like_single_line_plate_crop(plate_image):
            return recognition

        top, bottom = self._split_plate_top_bottom(recognition.get('plate_number', ''))
        if len(bottom) != 5 or not bottom.isdigit():
            return recognition

        digit_hints = self._read_bottom_line_digit_hints(plate_image, expected_digits=len(bottom))
        if len(digit_hints) != len(bottom):
            return recognition

        corrected = list(bottom)
        changed = False
        hint_confidences = []

        for idx, hint in enumerate(digit_hints):
            digit = hint.get('digit', '')
            confidence = float(hint.get('confidence', 0.0) or 0.0)
            if digit.isdigit() and confidence >= 0.88 and digit != corrected[idx]:
                corrected[idx] = digit
                changed = True
                hint_confidences.append(confidence)

        if not changed:
            return recognition

        corrected_plate = self._apply_plate_series_corrections(f"{top}-{''.join(corrected)}")
        if not self._is_plausible_plate_number(corrected_plate):
            return recognition

        updated = dict(recognition)
        updated['plate_number'] = corrected_plate
        updated['strategy'] = f"{recognition.get('strategy', 'ocr')}_two_line_char_corrected"
        updated['raw_text'] = recognition.get('raw_text', '')
        # Character-level correction is only a support signal, so keep confidence
        # conservative even when one corrected character is read very clearly.
        if hint_confidences:
            updated['confidence'] = max(
                float(recognition.get('confidence', 0.0) or 0.0),
                min(float(np.mean(hint_confidences)), 0.72)
            )
        return updated

    def _read_bottom_line_digit_hints(self, plate_image, expected_digits=5):
        if plate_image is None or plate_image.size == 0 or not self._ensure_easyocr_reader():
            return []

        h, w = plate_image.shape[:2]
        if h <= 0 or w <= 0:
            return []

        scale = max(4.0, 520 / max(1, w))
        scale = min(scale, 6.0)
        enlarged = cv2.resize(plate_image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        eh, ew = enlarged.shape[:2]
        bottom_crop = enlarged[int(eh * 0.42):int(eh * 0.96), :]
        if bottom_crop.size == 0:
            return []

        gray = cv2.cvtColor(bottom_crop, cv2.COLOR_BGR2GRAY) if len(bottom_crop.shape) == 3 else bottom_crop
        _threshold, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        contours, _hierarchy = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        image_h, image_w = gray.shape[:2]
        boxes = []

        for contour in contours:
            x, y, bw, bh = cv2.boundingRect(contour)
            if bh < image_h * 0.35 or bh > image_h * 0.92:
                continue
            if bw < image_w * 0.035 or bw > image_w * 0.18:
                continue
            if y + bh < image_h * 0.42:
                continue
            boxes.append((x, y, bw, bh))

        if len(boxes) < expected_digits:
            return []

        boxes.sort(key=lambda item: item[0])
        if len(boxes) > expected_digits:
            boxes = sorted(boxes, key=lambda item: item[2] * item[3], reverse=True)[:expected_digits]
            boxes.sort(key=lambda item: item[0])

        hints = []
        for x, y, bw, bh in boxes:
            pad = 8
            x1 = max(0, x - pad)
            y1 = max(0, y - pad)
            x2 = min(image_w, x + bw + pad)
            y2 = min(image_h, y + bh + pad)
            char_img = bottom_crop[y1:y2, x1:x2]
            if char_img.size == 0:
                hints.append({'digit': '', 'confidence': 0.0})
                continue

            char_img = cv2.resize(char_img, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
            try:
                result = self.ocr.readtext(
                    char_img,
                    detail=1,
                    allowlist='0123456789',
                    decoder='greedy',
                    batch_size=1,
                    workers=0
                )
            except Exception:
                result = []

            if result:
                best_char = max(result, key=lambda item: float(item[2] or 0.0))
                digit = re.sub(r'[^0-9]', '', str(best_char[1]))[:1]
                confidence = float(best_char[2] or 0.0) if digit else 0.0
            else:
                digit = ''
                confidence = 0.0
            hints.append({'digit': digit, 'confidence': confidence})

        return hints

    def _ensure_easyocr_reader(self):
        global easyocr, EASYOCR_AVAILABLE

        with self._ocr_lock:
            if EASYOCR_AVAILABLE is None:
                try:
                    import easyocr as easyocr_module
                    easyocr = easyocr_module
                    EASYOCR_AVAILABLE = True
                    utils.log_message("EasyOCR available and imported", 'INFO')
                except ImportError:
                    EASYOCR_AVAILABLE = False
                    utils.log_message("EasyOCR not available", 'WARNING')
                    return False

            if not EASYOCR_AVAILABLE:
                return False

            if self.ocr is None:
                try:
                    utils.log_message("Initializing EasyOCR reader...", 'INFO')
                    self.ocr = easyocr.Reader(['en'], gpu=False)
                    utils.log_message("EasyOCR reader initialized successfully", 'INFO')
                except Exception as e:
                    utils.log_message(f"Failed to initialize EasyOCR reader: {e}", 'ERROR')
                    return False

            return True

    def _recognize_webcam_phone_yolo_regions(self, image, max_regions=2, fast=True):
        """Detect plates inside the phone/display area before running OCR."""
        if not self.use_yolo or self.yolo_model is None or image is None or image.size == 0:
            return []

        image_h, image_w = image.shape[:2]
        image_area = max(1, image_h * image_w)
        boxes = []
        crop_specs = [
            ("phone_center_yolo", 0.16, 0.05, 0.90, 0.96),
            ("phone_plate_yolo", 0.20, 0.20, 0.88, 0.78),
        ]

        for crop_name, fx1, fy1, fx2, fy2 in crop_specs:
            x1 = max(0, min(image_w - 1, int(image_w * fx1)))
            y1 = max(0, min(image_h - 1, int(image_h * fy1)))
            x2 = max(x1 + 1, min(image_w, int(image_w * fx2)))
            y2 = max(y1 + 1, min(image_h, int(image_h * fy2)))
            crop = image[y1:y2, x1:x2]
            if crop.size == 0:
                continue

            try:
                detections = self.yolo_model(crop, conf=0.05, imgsz=640, verbose=False)
            except Exception as e:
                utils.log_message(f"Webcam phone YOLO scan failed ({crop_name}): {e}", 'DEBUG')
                continue

            for result in detections:
                if result.boxes is None or len(result.boxes) == 0:
                    continue
                for box in result.boxes:
                    bx1, by1, bx2, by2 = map(int, box.xyxy[0])
                    bw = max(1, bx2 - bx1)
                    bh = max(1, by2 - by1)
                    area_ratio = (bw * bh) / image_area
                    aspect = bw / max(1, bh)
                    if area_ratio > 0.20 or aspect < 0.55 or aspect > 6.5:
                        continue

                    pad_x = max(10, int(bw * 0.12))
                    pad_y = max(8, int(bh * 0.14))
                    ox1 = max(0, x1 + bx1 - pad_x)
                    oy1 = max(0, y1 + by1 - pad_y)
                    ox2 = min(image_w, x1 + bx2 + pad_x)
                    oy2 = min(image_h, y1 + by2 + pad_y)
                    if ox2 <= ox1 or oy2 <= oy1:
                        continue

                    confidence = float(box.conf[0]) if box.conf is not None else 0.0
                    boxes.append({
                        'bbox': (ox1, oy1, ox2 - ox1, oy2 - oy1),
                        'confidence': confidence,
                        'strategy': crop_name,
                        'score': confidence
                    })

        boxes.sort(key=lambda item: item['score'], reverse=True)
        kept = []
        for box in boxes:
            if any(self._bbox_iou_xywh(box['bbox'], existing['bbox']) > 0.50 for existing in kept):
                continue
            kept.append(box)
            if len(kept) >= max_regions:
                break

        results = []
        for box in kept:
            x, y, w, h = box['bbox']
            plate_crop = image[y:y + h, x:x + w]
            if plate_crop.size == 0:
                continue

            plate_crop, plate_bbox = self._tighten_plate_crop_repeated(plate_crop, box['bbox'])
            recognition = self._recognize_webcam_plate_crop(plate_crop, fast=fast)

            if not self._is_plausible_plate_number(recognition.get('plate_number', '')):
                continue

            recognition = dict(recognition)
            recognition['method'] = recognition.get('method') or 'webcam_phone_yolo'
            recognition['strategy'] = f"{box['strategy']}_{recognition.get('strategy', 'ocr')}"
            recognition['confidence'] = max(
                float(recognition.get('confidence', 0.0) or 0.0),
                float(box.get('confidence', 0.0) or 0.0) * 0.70
            )
            results.append({
                'bbox': plate_bbox,
                'recognition': recognition
            })

        return self._dedupe_plate_results(results)

    def _recognize_webcam_plate_crop(self, plate_crop, fast=True):
        """Read a webcam crop with a quick pass, then cross-check uncertain reads."""
        quick_result = self._recognize_with_quick_plate_ocr(plate_crop)
        quick_corrected = self._correct_wide_single_line_webcam_prefix(quick_result, plate_crop)
        if (
            self._is_plausible_plate_number(quick_corrected.get('plate_number', ''))
            and quick_corrected.get('plate_number') != quick_result.get('plate_number')
            and float(quick_corrected.get('confidence', 0.0) or 0.0) >= 0.60
        ):
            return quick_corrected

        candidates = []
        if self._is_plausible_plate_number(quick_corrected.get('plate_number', '')):
            candidates.append(dict(quick_corrected))

        quick_confidence = float(quick_result.get('confidence', 0.0) or 0.0)
        needs_crosscheck = (
            not self._is_plausible_plate_number(quick_result.get('plate_number', ''))
            or quick_confidence < 0.78
        )

        if needs_crosscheck:
            ocr_result = self._recognize_with_ocr(plate_crop, fast=True)
            if self._is_plausible_plate_number(ocr_result.get('plate_number', '')):
                candidates.append(dict(ocr_result))

            if self._looks_like_single_line_plate_crop(plate_crop):
                char_result = self._recognize_single_line_with_char_ocr(plate_crop)
                if self._is_plausible_plate_number((char_result or {}).get('plate_number', '')):
                    candidates.append(dict(char_result))

            if not fast and not candidates:
                slow_result = self._recognize_with_ocr(plate_crop, fast=False)
                if self._is_plausible_plate_number(slow_result.get('plate_number', '')):
                    candidates.append(dict(slow_result))

        if not candidates:
            return self._correct_wide_single_line_webcam_prefix(quick_result, plate_crop)

        selected = self._select_webcam_crop_ocr_result(candidates)
        return self._correct_wide_single_line_webcam_prefix(selected, plate_crop)

    def _correct_wide_single_line_webcam_prefix(self, recognition, plate_crop):
        """Fix OCR splits like 75A -> 17SA on wide one-line plates shown to webcam."""
        if not recognition or not self._is_plausible_plate_number(recognition.get('plate_number', '')):
            return recognition

        h, w = plate_crop.shape[:2]
        if h <= 0 or w / max(1, h) < 2.2:
            return recognition

        top, bottom = self._split_plate_top_bottom(recognition.get('plate_number', ''))
        if len(top) != 4 or len(bottom) not in {4, 5} or not bottom.isdigit():
            return recognition
        if not (top[0].isdigit() and top[1].isdigit() and top[2].isalpha() and top[3].isalpha()):
            return recognition

        middle_as_digit = self._to_digit_context(top[2])
        if not middle_as_digit:
            return recognition

        corrected_top = f"{top[1]}{middle_as_digit}{top[3]}"
        province = corrected_top[:2]
        if not province.isdigit() or not (10 <= int(province) <= 99):
            return recognition

        corrected_plate = f"{corrected_top}-{bottom}"
        corrected = dict(recognition)
        corrected['plate_number'] = corrected_plate
        corrected['strategy'] = f"{recognition.get('strategy', 'ocr')}_wide_prefix_correction"
        corrected['raw_text'] = recognition.get('raw_text', '') or recognition.get('plate_number', '')
        corrected['confidence'] = max(float(recognition.get('confidence', 0.0) or 0.0), 0.70)
        return corrected

    def _select_webcam_crop_ocr_result(self, candidates):
        counts = {}
        for candidate in candidates:
            plate_number = candidate.get('plate_number', '')
            counts[plate_number] = counts.get(plate_number, 0) + 1

        def rank(candidate):
            plate_number = candidate.get('plate_number', '')
            confidence = float(candidate.get('confidence', 0.0) or 0.0)
            score = self._score_plate_candidate(plate_number, confidence)
            score += self._score_raw_series_support(plate_number, candidate.get('raw_text', ''))
            score += (counts.get(plate_number, 0) - 1) * 2.2
            if candidate.get('method') == 'char_easyocr':
                score += 2.2
            if not str(candidate.get('strategy', '')).startswith('quick_'):
                score += 0.4
            if str(candidate.get('strategy', '')).startswith('quick_') and confidence < 0.78:
                score -= 1.4
            return score

        best = max(candidates, key=rank)
        return best

    def _recognize_webcam_phone_plate_regions(self, image, max_regions=2, fast=True):
        """OCR plate-like rectangles shown inside a phone screen in webcam frames."""
        results = []
        for crop, bbox, _score in self._find_webcam_phone_plate_regions(image, max_regions=max_regions):
            plate_crop, plate_bbox = self._tighten_plate_crop_repeated(crop, bbox)

            recognition = self._recognize_webcam_plate_crop(plate_crop, fast=fast)
            if not self._is_plausible_plate_number(recognition.get('plate_number', '')):
                continue

            recognition = dict(recognition)
            recognition['method'] = recognition.get('method') or 'webcam_phone_ocr'
            recognition['strategy'] = f"phone_region_{recognition.get('strategy', 'ocr')}"
            results.append({
                'bbox': plate_bbox,
                'recognition': recognition
            })

        return self._dedupe_plate_results(results)

    def _find_webcam_phone_plate_regions(self, image, max_regions=3):
        """Find bright plate rectangles in noisy webcam frames, especially on phones."""
        if image is None or image.size == 0:
            return []

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        image_h, image_w = gray.shape[:2]
        image_area = max(1, image_h * image_w)

        thresholds = {90, 105, 120, 135, 150}
        for percentile in (58, 64, 70, 76, 82, 88):
            thresholds.add(max(75, int(np.percentile(blurred, percentile))))

        kernels = [
            cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5)),
            cv2.getStructuringElement(cv2.MORPH_RECT, (15, 7)),
        ]
        candidates = []

        for threshold in thresholds:
            base_mask = cv2.inRange(blurred, threshold, 255)
            for kernel in kernels:
                mask = cv2.morphologyEx(base_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
                contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                for contour in contours:
                    x, y, w, h = cv2.boundingRect(contour)
                    if w <= 0 or h <= 0:
                        continue

                    area_ratio = (w * h) / image_area
                    aspect = w / max(1, h)
                    if area_ratio < 0.0012 or area_ratio > 0.22:
                        continue
                    if w < image_w * 0.06 or h < image_h * 0.035:
                        continue
                    if aspect < 1.05 or aspect > 7.2:
                        continue

                    # Avoid choosing large UI/phone bars near the frame edges.
                    center_x = (x + w / 2) / max(1, image_w)
                    center_y = (y + h / 2) / max(1, image_h)
                    if center_x < 0.10 or center_x > 0.92 or center_y < 0.08 or center_y > 0.92:
                        continue

                    roi_gray = gray[y:y + h, x:x + w]
                    if roi_gray.size == 0:
                        continue

                    mean_intensity = float(np.mean(roi_gray))
                    if mean_intensity < 70:
                        continue

                    dark_threshold = min(135, max(35, int(mean_intensity - 38)))
                    dark_ratio = float(np.mean(roi_gray < dark_threshold))
                    edge_ratio = float(np.mean(cv2.Canny(roi_gray, 60, 160) > 0))
                    if dark_ratio < 0.018 and edge_ratio < 0.020:
                        continue

                    center_score = 1.0 - min(
                        abs(center_x - 0.52) / 0.52 + abs(center_y - 0.50) / 0.50,
                        1.0
                    )
                    aspect_target = 3.4 if aspect >= 2.0 else 1.45
                    aspect_score = 1.0 - min(abs(aspect - aspect_target) / aspect_target, 1.0)
                    text_score = min(dark_ratio * 8.0, 1.0) + min(edge_ratio * 12.0, 1.0)
                    score = aspect_score * 1.8 + text_score * 1.2 + center_score * 0.45 + min(area_ratio * 8.0, 1.0)

                    pad_x = max(8, int(w * 0.10))
                    pad_y = max(6, int(h * 0.18))
                    x1 = max(0, x - pad_x)
                    y1 = max(0, y - pad_y)
                    x2 = min(image_w, x + w + pad_x)
                    y2 = min(image_h, y + h + pad_y)
                    crop = image[y1:y2, x1:x2]
                    if crop.size == 0:
                        continue

                    candidates.append({
                        'crop': crop,
                        'bbox': (x1, y1, x2 - x1, y2 - y1),
                        'score': score
                    })

        candidates.sort(key=lambda item: item['score'], reverse=True)
        kept = []
        for candidate in candidates:
            if any(self._bbox_iou_xywh(candidate['bbox'], existing['bbox']) > 0.45 for existing in kept):
                continue
            kept.append(candidate)
            if len(kept) >= max_regions:
                break

        return [(item['crop'], item['bbox'], item['score']) for item in kept]

    def _recognize_with_quick_plate_ocr(self, plate_image):
        """Low-latency OCR for webcam crops; return after the first solid plate."""
        if not self._ensure_easyocr_reader():
            return {
                'method': 'error',
                'plate_number': 'UNKNOWN',
                'confidence': 0.0,
                'raw_text': ''
            }

        h, w = plate_image.shape[:2]
        if w < 300 or h < 90:
            scale = max(300 / max(1, w), 90 / max(1, h))
            scale = min(scale, 2.8)
            plate_image = cv2.resize(plate_image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

        strategies = [
            ("direct", plate_image),
            ("clahe", self._preprocess_clahe(plate_image)),
            ("sharpen", self._preprocess_sharpen(plate_image)),
            ("adaptive", self._preprocess_adaptive(plate_image)),
            ("otsu", self._preprocess_otsu(plate_image)),
        ]
        best_result = {
            'method': 'error',
            'plate_number': 'UNKNOWN',
            'confidence': 0.0,
            'raw_text': ''
        }
        best_score = 0.0
        candidates = []

        for strategy_name, processed_img in strategies:
            try:
                if len(processed_img.shape) == 2:
                    processed_img = cv2.cvtColor(processed_img, cv2.COLOR_GRAY2BGR)

                ocr_results = self.ocr.readtext(
                    processed_img,
                    detail=1,
                    allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-. '
                )
                candidate = self._build_ocr_candidate(ocr_results)
                if not candidate:
                    continue

                plate_number = candidate['plate_number']
                confidence = float(candidate['confidence'])
                score = self._score_plate_candidate(plate_number, confidence)
                score += self._score_raw_series_support(plate_number, candidate['raw_text'])
                result = {
                    'method': 'easyocr',
                    'strategy': f"quick_{strategy_name}",
                    'plate_number': plate_number,
                    'confidence': confidence,
                    'raw_text': candidate['raw_text'],
                    'score': score
                }
                candidates.append(result)

                if score > best_score:
                    best_score = score
                    best_result = result

            except Exception as e:
                utils.log_message(f"Quick webcam OCR failed ({strategy_name}): {e}", 'DEBUG')

        if candidates:
            best_result = self._choose_consensus_ocr_result(candidates, best_result)

        return best_result

    def _detect_plates_with_full_frame_ocr(
        self,
        image,
        max_bright_regions=None,
        allow_full_frame=True,
        square_extra=False,
        stop_after_first_candidate=False,
        max_ocr_strategies=None
    ):
        """Fallback for webcam frames where the plate is shown on a phone screen."""
        if not self._ensure_easyocr_reader():
            return []

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        bright_regions = self._find_bright_plate_like_regions(image)
        if max_bright_regions:
            bright_regions = bright_regions[:max_bright_regions]
        if not bright_regions and float(np.mean(gray)) < 28 and float(np.percentile(gray, 99)) < 90:
            utils.log_message("Skipping full-frame OCR fallback: frame is too dark", 'DEBUG')
            return []

        best_candidates = {}

        strategy_count = 0
        for strategy_name, processed_img, scale_x, scale_y, offset_x, offset_y in self._full_frame_ocr_strategies(
            image,
            bright_regions,
            allow_full_frame=allow_full_frame,
            square_extra=square_extra
        ):
            if max_ocr_strategies is not None and strategy_count >= max_ocr_strategies:
                break
            strategy_count += 1
            try:
                if len(processed_img.shape) == 2:
                    processed_img = cv2.cvtColor(processed_img, cv2.COLOR_GRAY2BGR)

                read_scale_x = scale_x
                read_scale_y = scale_y
                max_side = max(processed_img.shape[:2])
                if max_side > 900:
                    resize_ratio = 900 / max_side
                    processed_img = cv2.resize(
                        processed_img,
                        None,
                        fx=resize_ratio,
                        fy=resize_ratio,
                        interpolation=cv2.INTER_AREA
                    )
                    read_scale_x *= resize_ratio
                    read_scale_y *= resize_ratio

                ocr_results = self.ocr.readtext(
                    processed_img,
                    detail=1,
                    allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-. ',
                    decoder='greedy',
                    batch_size=1,
                    workers=0,
                    canvas_size=900,
                    mag_ratio=1.0,
                    text_threshold=0.35,
                    low_text=0.20,
                    link_threshold=0.20
                )
                detections = []

                for bbox, text, confidence in ocr_results:
                    original_bbox = self._map_ocr_points_to_original(bbox, read_scale_x, read_scale_y, offset_x, offset_y)
                    detections.append({
                        'bbox_points': original_bbox,
                        'text': text,
                        'confidence': float(confidence or 0.0)
                    })
                    self._add_full_frame_ocr_candidate(
                        best_candidates,
                        image.shape,
                        original_bbox,
                        text,
                        confidence,
                        strategy_name
                    )

                self._add_combined_full_frame_ocr_candidates(best_candidates, image.shape, detections, strategy_name)
                if stop_after_first_candidate and best_candidates:
                    break
            except Exception as e:
                utils.log_message(f"Full-frame OCR fallback failed ({strategy_name}): {e}", 'DEBUG')

        candidates = sorted(best_candidates.values(), key=lambda item: item['score'], reverse=True)
        results = []
        for candidate in candidates[:2]:
            results.append({
                'bbox': candidate['bbox'],
                'recognition': {
                    'method': 'full_frame_easyocr',
                    'strategy': candidate['strategy'],
                    'plate_number': candidate['plate_number'],
                    'confidence': candidate['confidence'],
                    'raw_text': candidate['raw_text']
                }
            })

        if results:
            utils.log_message(f"Full-frame OCR fallback detected {len(results)} plate candidates", 'INFO')
        return results

    def _full_frame_ocr_strategies(self, image, bright_regions=None, allow_full_frame=True, square_extra=False):
        h, w = image.shape[:2]
        bright_regions = bright_regions if bright_regions is not None else self._find_bright_plate_like_regions(image)

        if square_extra and len(bright_regions) >= 2:
            for idx, (first, second) in enumerate(self._merge_vertical_bright_regions(image, bright_regions)):
                region, rx, ry = first
                if region.size == 0:
                    continue
                region_scale = max(2.0, 420 / max(region.shape[1], 1))
                region_scale = min(region_scale, 5.0)
                direct_prepared = cv2.resize(region, None, fx=region_scale, fy=region_scale, interpolation=cv2.INTER_CUBIC)
                yield (f"bright_two_line_plate_{idx}_direct", direct_prepared, region_scale, region_scale, rx, ry)
                adaptive_prepared = cv2.resize(self._preprocess_adaptive(region), None, fx=region_scale, fy=region_scale, interpolation=cv2.INTER_CUBIC)
                yield (f"bright_two_line_plate_{idx}_adaptive", adaptive_prepared, region_scale, region_scale, rx, ry)

        for idx, (region, rx, ry) in enumerate(bright_regions):
            if region.size == 0:
                continue
            region_scale = max(2.0, 360 / max(region.shape[1], 1))
            region_scale = min(region_scale, 5.0)
            if square_extra:
                direct_prepared = cv2.resize(region, None, fx=region_scale, fy=region_scale, interpolation=cv2.INTER_CUBIC)
                yield (f"bright_plate_region_{idx}_direct", direct_prepared, region_scale, region_scale, rx, ry)

            prepared = cv2.resize(self._preprocess_sharpen(region), None, fx=region_scale, fy=region_scale, interpolation=cv2.INTER_CUBIC)
            yield (f"bright_plate_region_{idx}", prepared, region_scale, region_scale, rx, ry)

            region_aspect = region.shape[1] / max(1, region.shape[0])
            if square_extra and region_aspect < 2.2:
                otsu_prepared = cv2.resize(self._preprocess_otsu(region), None, fx=region_scale, fy=region_scale, interpolation=cv2.INTER_CUBIC)
                yield (f"bright_square_region_{idx}_otsu", otsu_prepared, region_scale, region_scale, rx, ry)
                adaptive_prepared = cv2.resize(self._preprocess_adaptive(region), None, fx=region_scale, fy=region_scale, interpolation=cv2.INTER_CUBIC)
                yield (f"bright_square_region_{idx}_adaptive", adaptive_prepared, region_scale, region_scale, rx, ry)

        if not allow_full_frame:
            return

        for crop_name, crop_box in self._phone_screen_ocr_crops(image):
            crop, x1, y1 = crop_box
            if crop.size == 0:
                continue
            crop_scale = max(2.0, 520 / max(crop.shape[1], 1))
            crop_scale = min(crop_scale, 3.6)

            sharpen_prepared = cv2.resize(self._preprocess_sharpen(crop), None, fx=crop_scale, fy=crop_scale, interpolation=cv2.INTER_CUBIC)
            yield (f"{crop_name}_sharpen", sharpen_prepared, crop_scale, crop_scale, x1, y1)

            if crop_name == "phone_plate_band":
                adaptive_prepared = cv2.resize(self._preprocess_adaptive(crop), None, fx=crop_scale, fy=crop_scale, interpolation=cv2.INTER_CUBIC)
                yield (f"{crop_name}_adaptive", adaptive_prepared, crop_scale, crop_scale, x1, y1)

        x1 = int(w * 0.08)
        y1 = int(h * 0.08)
        x2 = int(w * 0.92)
        y2 = int(h * 0.92)
        crop = image[y1:y2, x1:x2]
        if crop.size > 0:
            crop_scale = 1.8
            crop_prepared = cv2.resize(self._preprocess_sharpen(crop), None, fx=crop_scale, fy=crop_scale, interpolation=cv2.INTER_CUBIC)
            yield ("center_crop_upscaled", crop_prepared, crop_scale, crop_scale, x1, y1)

        if not square_extra:
            scale = 1.4
            upscaled = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            yield ("full_frame_upscaled", upscaled, scale, scale, 0, 0)

    def _phone_screen_ocr_crops(self, image):
        """Crops for a plate image shown on a phone in the center of the webcam frame."""
        h, w = image.shape[:2]
        crop_specs = [
            ("phone_plate_band", 0.24, 0.24, 0.86, 0.72),
            ("phone_center", 0.22, 0.08, 0.84, 0.96),
        ]

        crops = []
        for name, fx1, fy1, fx2, fy2 in crop_specs:
            x1 = max(0, min(w - 1, int(w * fx1)))
            y1 = max(0, min(h - 1, int(h * fy1)))
            x2 = max(x1 + 1, min(w, int(w * fx2)))
            y2 = max(y1 + 1, min(h, int(h * fy2)))
            crop = image[y1:y2, x1:x2]
            crops.append((name, (crop, x1, y1)))
        return crops

    def _merge_vertical_bright_regions(self, image, bright_regions):
        """Merge stacked bright text bands from square motorcycle plates."""
        image_h, image_w = image.shape[:2]
        boxes = []
        for region, x, y in bright_regions[:5]:
            rh, rw = region.shape[:2]
            if rw <= 0 or rh <= 0:
                continue
            boxes.append((x, y, x + rw, y + rh))

        merged = []
        for i, first in enumerate(boxes):
            for second in boxes[i + 1:]:
                x1a, y1a, x2a, y2a = first
                x1b, y1b, x2b, y2b = second
                center_delta = abs(((x1a + x2a) / 2) - ((x1b + x2b) / 2))
                max_width = max(x2a - x1a, x2b - x1b)
                vertical_gap = max(0, max(y1a, y1b) - min(y2a, y2b))
                union_x1 = min(x1a, x1b)
                union_y1 = min(y1a, y1b)
                union_x2 = max(x2a, x2b)
                union_y2 = max(y2a, y2b)
                union_w = union_x2 - union_x1
                union_h = union_y2 - union_y1
                if union_w <= 0 or union_h <= 0:
                    continue
                union_aspect = union_w / max(1, union_h)

                if center_delta > max_width * 0.75:
                    continue
                if vertical_gap > image_h * 0.24:
                    continue
                if union_aspect < 0.45 or union_aspect > 3.8:
                    continue

                pad_x = max(10, int(union_w * 0.20))
                pad_y = max(10, int(union_h * 0.18))
                crop_x1 = max(0, union_x1 - pad_x)
                crop_y1 = max(0, union_y1 - pad_y)
                crop_x2 = min(image_w, union_x2 + pad_x)
                crop_y2 = min(image_h, union_y2 + pad_y)
                crop = image[crop_y1:crop_y2, crop_x1:crop_x2]
                if crop.size:
                    merged.append(((crop, crop_x1, crop_y1), (union_w * union_h)))

        merged.sort(key=lambda item: item[1], reverse=True)
        return merged[:3]

    @staticmethod
    def _find_bright_plate_like_regions(image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        threshold_value = max(65, int(np.percentile(blurred, 70)))
        mask = cv2.inRange(blurred, threshold_value, 255)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        image_h, image_w = image.shape[:2]
        image_area = image_h * image_w
        regions = []

        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w <= 0 or h <= 0:
                continue

            area = w * h
            aspect = w / h
            if area < image_area * 0.0007 or area > image_area * 0.35:
                continue
            if aspect < 0.75 or aspect > 8.0:
                continue

            roi_gray = gray[y:y + h, x:x + w]
            if roi_gray.size == 0 or float(np.mean(roi_gray)) < 70:
                continue

            dark_threshold = min(115, max(35, int(np.mean(roi_gray) - 28)))
            dark_ratio = float(np.mean(roi_gray < dark_threshold))
            edge_ratio = float(np.mean(cv2.Canny(roi_gray, 60, 160) > 0))
            if dark_ratio < 0.010 and edge_ratio < 0.018:
                continue

            padding_x = max(8, int(w * 0.08))
            padding_y = max(8, int(h * 0.12))
            x1 = max(0, x - padding_x)
            y1 = max(0, y - padding_y)
            x2 = min(image_w, x + w + padding_x)
            y2 = min(image_h, y + h + padding_y)
            region = image[y1:y2, x1:x2]
            plate_aspect_score = 1.0 - min(abs(aspect - 2.6) / 2.6, 1.0)
            text_score = min(dark_ratio * 6.0, 1.0) + min(edge_ratio * 8.0, 1.0)
            score = area * (0.35 + plate_aspect_score + text_score)
            regions.append((region, x1, y1, score))

        regions.sort(key=lambda item: item[3], reverse=True)
        return [(region, x, y) for region, x, y, _score in regions[:5]]

    @staticmethod
    def _map_ocr_points_to_original(bbox_points, scale_x, scale_y, offset_x, offset_y):
        mapped = []
        for point in bbox_points:
            mapped.append([
                float(point[0]) / scale_x + offset_x,
                float(point[1]) / scale_y + offset_y
            ])
        return mapped

    def _add_full_frame_ocr_candidate(self, candidates, image_shape, bbox_points, text, confidence, strategy_name):
        normalized = self._normalize_vietnamese_plate_candidate(self._clean_plate_text(text))
        if not self._is_plausible_plate_number(normalized):
            return

        bbox = self._ocr_bbox_to_xywh(bbox_points, image_shape)
        if not bbox:
            return

        compact_len = len(re.sub(r'[^A-Z0-9]', '', normalized))
        score = float(confidence or 0.0) * compact_len
        existing = candidates.get(normalized)
        if not existing or score > existing['score']:
            candidates[normalized] = {
                'bbox': bbox,
                'plate_number': normalized,
                'confidence': float(confidence or 0.0),
                'raw_text': text,
                'strategy': strategy_name,
                'score': score
            }

    def _add_combined_full_frame_ocr_candidates(self, candidates, image_shape, detections, strategy_name):
        if len(detections) < 2:
            return

        for i, first in enumerate(detections):
            for second in detections[i + 1:]:
                bbox1 = self._ocr_bbox_to_xywh(first['bbox_points'], image_shape, padding=0)
                bbox2 = self._ocr_bbox_to_xywh(second['bbox_points'], image_shape, padding=0)
                if not bbox1 or not bbox2:
                    continue

                x1, y1, w1, h1 = bbox1
                x2, y2, w2, h2 = bbox2
                center_delta = abs((x1 + w1 / 2) - (x2 + w2 / 2))
                max_width = max(w1, w2)
                vertical_gap = abs(y2 - y1)

                if center_delta > max_width or vertical_gap > image_shape[0] * 0.22:
                    continue

                ordered = sorted([first, second], key=lambda item: self._ocr_bbox_to_xywh(item['bbox_points'], image_shape, padding=0)[1])
                text = ''.join(item['text'] for item in ordered)
                confidence = float(np.mean([item['confidence'] for item in ordered]))
                union_points = list(first['bbox_points']) + list(second['bbox_points'])
                self._add_full_frame_ocr_candidate(candidates, image_shape, union_points, text, confidence, strategy_name + '_combined')

    @staticmethod
    def _ocr_bbox_to_xywh(bbox_points, image_shape, padding=8):
        if not bbox_points:
            return None

        points = np.array(bbox_points, dtype=np.float32).reshape(-1, 2)
        x1 = max(0, int(np.floor(points[:, 0].min())) - padding)
        y1 = max(0, int(np.floor(points[:, 1].min())) - padding)
        x2 = min(image_shape[1], int(np.ceil(points[:, 0].max())) + padding)
        y2 = min(image_shape[0], int(np.ceil(points[:, 1].max())) + padding)
        width = x2 - x1
        height = y2 - y1
        if width <= 0 or height <= 0:
            return None
        return (x1, y1, width, height)
    
    def _preprocess_grayscale(self, img):
        """Convert to grayscale"""
        if len(img.shape) == 3:
            return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return img
    
    def _preprocess_clahe(self, img):
        """Apply CLAHE contrast enhancement"""
        gray = self._preprocess_grayscale(img)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        return clahe.apply(gray)
    
    def _preprocess_sharpen(self, img):
        """Sharpen image"""
        clahe_img = self._preprocess_clahe(img)
        kernel = np.array([[0, -1, 0],
                          [-1, 5, -1],
                          [0, -1, 0]], dtype=np.float32)
        return cv2.filter2D(clahe_img, -1, kernel)

    def _preprocess_otsu(self, img):
        """High-contrast binary image for small two-line plates."""
        clahe_img = self._preprocess_clahe(img)
        _threshold, binary = cv2.threshold(clahe_img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binary

    def _preprocess_adaptive(self, img):
        """Adaptive threshold for low-light webcam frames and phone-screen glare."""
        clahe_img = self._preprocess_clahe(img)
        return cv2.adaptiveThreshold(
            clahe_img,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            9
        )

    def _tighten_plate_crop_repeated(self, plate_image, original_bbox=None, max_passes=2):
        crop = plate_image
        bbox = original_bbox
        if crop is not None and crop.size:
            image_h, image_w = crop.shape[:2]
            if image_h > 0 and (image_w / image_h) < 2.25:
                # For square/two-line plates, the loose YOLO crop usually
                # preserves the first/last characters better than contour
                # tightening. The old repeated tighten cut "51H 881.24" down
                # to "1H ..." and made OCR fail.
                return crop, bbox

        for _ in range(max_passes):
            tightened = self._tighten_plate_crop(crop, bbox)
            if not tightened:
                break

            next_crop, next_bbox = tightened
            current_area = max(1, crop.shape[0] * crop.shape[1])
            next_area = max(1, next_crop.shape[0] * next_crop.shape[1])
            current_h, current_w = crop.shape[:2]
            next_h, next_w = next_crop.shape[:2]
            if current_w > 0 and current_h > 0:
                width_ratio = next_w / current_w
                height_ratio = next_h / current_h
                next_aspect = next_w / max(1, next_h)
                if width_ratio < 0.72 or height_ratio < 0.62 or next_aspect < 1.50:
                    break

            crop, bbox = next_crop, next_bbox
            if next_area / current_area > 0.94:
                break

        return crop, bbox

    def _tighten_plate_crop(self, plate_image, original_bbox=None):
        """Trim a loose detector crop back to the bright plate rectangle."""
        if plate_image is None or plate_image.size == 0:
            return None

        image_h, image_w = plate_image.shape[:2]
        if image_w < 40 or image_h < 18:
            return None

        gray = cv2.cvtColor(plate_image, cv2.COLOR_BGR2GRAY) if len(plate_image.shape) == 3 else plate_image
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        thresholds = {
            max(95, int(np.percentile(blurred, percentile)))
            for percentile in (58, 63, 68, 73, 78, 83)
        }
        otsu_threshold, _binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        thresholds.add(max(95, int(otsu_threshold)))

        crop_area = image_w * image_h
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5))
        best = None
        best_score = -1.0

        for threshold in thresholds:
            mask = cv2.inRange(blurred, threshold, 255)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
            contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                if w <= 0 or h <= 0:
                    continue

                area_ratio = (w * h) / max(1, crop_area)
                aspect = w / max(1, h)
                if area_ratio < 0.12 or area_ratio > 0.92:
                    continue
                if w < image_w * 0.42 or h < image_h * 0.32:
                    continue
                if aspect < 1.25 or aspect > 5.8:
                    continue

                center_x = x + w / 2
                center_y = y + h / 2
                center_score = 1.0 - min(
                    abs(center_x - image_w / 2) / max(1, image_w / 2),
                    1.0
                )
                vertical_score = 1.0 - min(
                    abs(center_y - image_h / 2) / max(1, image_h / 2),
                    1.0
                )
                aspect_target = 3.4 if aspect > 2.0 else 1.45
                aspect_score = 1.0 - min(abs(aspect - aspect_target) / aspect_target, 1.0)
                edge_penalty = 0.0
                if x <= 2 or y <= 2 or x + w >= image_w - 2 or y + h >= image_h - 2:
                    edge_penalty = 0.45

                score = aspect_score * 1.7 + center_score * 0.45 + vertical_score * 0.35 + min(area_ratio, 0.65) - edge_penalty
                if score > best_score:
                    best_score = score
                    best = (x, y, w, h)

        if not best:
            return None

        x, y, w, h = best
        if (w * h) / max(1, crop_area) > 0.88:
            return None

        pad_x = max(2, int(w * 0.025))
        pad_y = max(2, int(h * 0.035))
        x1 = max(0, x - pad_x)
        y1 = max(0, y - pad_y)
        x2 = min(image_w, x + w + pad_x)
        y2 = min(image_h, y + h + pad_y)
        tightened = plate_image[y1:y2, x1:x2]
        if tightened.size == 0:
            return None

        if original_bbox is None:
            adjusted_bbox = (x1, y1, x2 - x1, y2 - y1)
        else:
            bx, by, _bw, _bh = original_bbox
            adjusted_bbox = (int(bx) + x1, int(by) + y1, x2 - x1, y2 - y1)

        utils.log_message(
            f"Tightened plate crop from {image_w}x{image_h} to {x2 - x1}x{y2 - y1}",
            'DEBUG'
        )
        return tightened, adjusted_bbox

    def _recognize_single_line_with_char_ocr(self, plate_image):
        """Segment a clear one-line plate and OCR each character with position rules."""
        if not self._ensure_easyocr_reader():
            return None

        char_boxes = self._segment_single_line_char_boxes(plate_image)
        if len(char_boxes) not in {7, 8, 9}:
            return None

        gray = self._preprocess_grayscale(plate_image)
        recognized = []
        confidences = []

        for idx, (x, y, w, h) in enumerate(char_boxes):
            pad_x = max(3, int(w * 0.18))
            pad_y = max(3, int(h * 0.12))
            x1 = max(0, x - pad_x)
            y1 = max(0, y - pad_y)
            x2 = min(gray.shape[1], x + w + pad_x)
            y2 = min(gray.shape[0], y + h + pad_y)
            char_img = gray[y1:y2, x1:x2]
            if char_img.size == 0:
                return None

            scale = max(4.0, 120 / max(1, char_img.shape[0]))
            scale = min(scale, 6.0)
            prepared = cv2.resize(char_img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            prepared = cv2.cvtColor(prepared, cv2.COLOR_GRAY2BGR)

            if idx in {0, 1} or idx >= 3:
                allowlist = '0123456789'
            else:
                allowlist = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
            try:
                result = []
                variants = [
                    prepared,
                    cv2.cvtColor(
                        self._preprocess_otsu(cv2.cvtColor(prepared, cv2.COLOR_BGR2GRAY)),
                        cv2.COLOR_GRAY2BGR
                    )
                ]
                for variant in variants:
                    run = self.ocr.readtext(
                        variant,
                        detail=1,
                        allowlist=allowlist,
                        decoder='greedy',
                        batch_size=1,
                        workers=0,
                        canvas_size=256,
                        mag_ratio=1.0
                    )
                    if run:
                        result.extend(run)
            except Exception as e:
                utils.log_message(f"Character OCR failed: {e}", 'DEBUG')
                return None

            if result:
                best_char = max(result, key=lambda item: float(item[2] or 0.0))
                text = self._clean_plate_text(best_char[1])[:1]
                confidence = float(best_char[2] or 0.0)
            else:
                text = ''
                confidence = 0.0

            if not text:
                return None

            recognized.append(text)
            confidences.append(confidence)

        raw_text = ''.join(recognized)
        plate_number = self._normalize_single_line_chars(raw_text)
        if not self._is_plausible_plate_number(plate_number):
            return None

        avg_confidence = float(np.mean(confidences)) if confidences else 0.0
        return {
            'method': 'char_easyocr',
            'strategy': 'single_line_char_ocr',
            'plate_number': plate_number,
            'confidence': avg_confidence,
            'raw_text': raw_text
        }

    def _segment_single_line_char_boxes(self, plate_image):
        gray = self._preprocess_grayscale(plate_image)
        _threshold, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        contours, _hierarchy = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        image_h, image_w = gray.shape[:2]
        raw_boxes = []

        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if h < image_h * 0.32 or h > image_h * 0.92:
                continue
            if w < 3 or w > image_w * 0.18:
                continue
            if y < image_h * 0.02 or y + h > image_h * 0.98:
                continue
            raw_boxes.append((x, y, w, h))

        boxes = []
        for box in sorted(raw_boxes, key=lambda item: item[2] * item[3], reverse=True):
            if any(self._bbox_iou_xywh(box, kept) > 0.35 for kept in boxes):
                continue
            boxes.append(box)

        if len(boxes) < 7:
            return []

        boxes.sort(key=lambda item: item[0])
        median_h = float(np.median([box[3] for box in boxes]))
        filtered = [
            box for box in boxes
            if box[3] >= median_h * 0.72
        ]

        if len(filtered) < 7:
            return []

        return filtered[:9]

    def _normalize_single_line_chars(self, raw_text):
        compact = re.sub(r'[^A-Z0-9]', '', (raw_text or '').upper())
        if len(compact) < 7:
            return ''

        province = ''.join(self._to_digit_context(ch) for ch in compact[:2])
        series = self._to_series_context(compact[2])
        tail = ''.join(self._to_digit_context(ch) for ch in compact[3:])
        if len(tail) > 5:
            tail = tail[-5:]
        return f"{province}{series}-{tail}" if tail else f"{province}{series}"

    def _build_ocr_candidate(self, ocr_results):
        detections_with_pos = []

        for detection in ocr_results:
            bbox = detection[0]
            text = detection[1].strip()
            confidence = float(detection[2] or 0.0)
            if not text:
                continue

            x_pos = min(point[0] for point in bbox) if bbox else 0
            y_pos = min(point[1] for point in bbox) if bbox else 0
            detections_with_pos.append({
                'text': text,
                'confidence': confidence,
                'x_pos': x_pos,
                'y_pos': y_pos
            })

        if not detections_with_pos:
            return None

        detections_with_pos.sort(key=lambda x: x['y_pos'])
        y_positions = [d['y_pos'] for d in detections_with_pos]
        y_median = (min(y_positions) + max(y_positions)) / 2

        top_line_items = sorted(
            [d for d in detections_with_pos if d['y_pos'] < y_median],
            key=lambda item: item['x_pos']
        )
        bottom_line_items = sorted(
            [d for d in detections_with_pos if d['y_pos'] >= y_median],
            key=lambda item: item['x_pos']
        )
        top_line = [d['text'] for d in top_line_items]
        bottom_line = [d['text'] for d in bottom_line_items]

        top_text = self._clean_plate_text("".join(top_line))
        bottom_text = self._clean_plate_text("".join(bottom_line))

        if top_text and bottom_text:
            raw_text = f"{top_text}-{bottom_text}"
        elif top_text:
            raw_text = top_text
        elif bottom_text:
            raw_text = bottom_text
        else:
            return None

        plate_number = self._normalize_vietnamese_plate_candidate(raw_text)
        if not plate_number:
            return None

        confidences = [d['confidence'] for d in detections_with_pos]
        return {
            'plate_number': plate_number,
            'confidence': float(np.mean(confidences)) if confidences else 0.0,
            'raw_text': raw_text
        }

    def _score_plate_candidate(self, plate_number, confidence):
        compact_len = len(re.sub(r'[^A-Z0-9]', '', plate_number or ''))
        plausible = self._is_plausible_plate_number(plate_number)
        if not plausible:
            # Do not let long garbage such as "1-T1221-11221" beat a shorter
            # valid plate just because EasyOCR returned a higher confidence.
            overflow_penalty = max(0, compact_len - 9) * 1.8
            return min(float(confidence or 0.0) * compact_len, 2.0) - overflow_penalty

        score = float(confidence or 0.0) * compact_len

        score += 4.0

        parts = [p for p in re.split(r'-+', plate_number or '') if p]
        if len(parts) >= 2:
            top = re.sub(r'[^A-Z0-9]', '', ''.join(parts[:-1]))
            bottom = re.sub(r'[^0-9]', '', parts[-1])
            if len(top) == 4 and len(bottom) in {4, 5}:
                score += 1.2
            if len(bottom) == 5:
                score += 1.0

        return score

    def _score_raw_series_support(self, plate_number, raw_text):
        """Prefer a directly-read series letter over a digit that was mapped later."""
        compact_plate = re.sub(r'[^A-Z0-9]', '', (plate_number or '').upper())
        compact_raw = re.sub(r'[^A-Z0-9]', '', (raw_text or '').upper())
        if len(compact_plate) < 3 or len(compact_raw) < 3:
            return 0.0

        normalized_series = compact_plate[2]
        raw_series = compact_raw[2]
        if not normalized_series.isalpha():
            return 0.0

        if raw_series == normalized_series:
            return 0.9

        if raw_series.isdigit():
            mapped_series = self._to_series_context(raw_series)
            if mapped_series == normalized_series:
                # The most common false positive in this app is 1 -> T on a
                # true "A" series plate. Keep the candidate possible, but make
                # it lose when another preprocessing read a real letter.
                if raw_series == '1' and normalized_series == 'T':
                    return -2.2
                return -0.45

        return 0.0

    def _dedupe_plate_results(self, plates):
        if not plates:
            return []

        def result_rank(plate):
            recognition = plate.get('recognition', {})
            plate_number = recognition.get('plate_number', '')
            confidence = float(recognition.get('confidence', 0.0) or 0.0)
            plausible_bonus = 3.0 if self._is_plausible_plate_number(plate_number) else 0.0
            method_bonus = 0.8 if recognition.get('method') == 'char_easyocr' else 0.0
            return plausible_bonus + method_bonus + confidence

        sorted_plates = sorted(plates, key=result_rank, reverse=True)
        kept = []
        for plate in sorted_plates:
            bbox = plate.get('bbox')
            if any(self._bbox_iou_xywh(bbox, existing.get('bbox')) > 0.35 for existing in kept):
                continue
            kept.append(plate)

        if any(self._is_plausible_plate_number(p.get('recognition', {}).get('plate_number', '')) for p in kept):
            kept = [
                p for p in kept
                if self._is_plausible_plate_number(p.get('recognition', {}).get('plate_number', ''))
            ]

        return sorted(kept, key=result_rank, reverse=True)

    @staticmethod
    def _bbox_iou_xywh(first, second):
        if not first or not second:
            return 0.0
        x1, y1, w1, h1 = [float(v) for v in first]
        x2, y2, w2, h2 = [float(v) for v in second]
        ax2, ay2 = x1 + w1, y1 + h1
        bx2, by2 = x2 + w2, y2 + h2
        inter_w = max(0.0, min(ax2, bx2) - max(x1, x2))
        inter_h = max(0.0, min(ay2, by2) - max(y1, y2))
        inter = inter_w * inter_h
        area_a = max(0.0, w1) * max(0.0, h1)
        area_b = max(0.0, w2) * max(0.0, h2)
        union = area_a + area_b - inter
        return inter / union if union > 0 else 0.0

    def _split_plate_top_bottom(self, plate_number):
        text = (plate_number or '').upper()
        compact = re.sub(r'[^A-Z0-9]', '', text)
        parts = [p for p in re.split(r'-+', text) if p]
        if len(parts) >= 2:
            top = ''.join(parts[:-1])
            bottom = parts[-1]
        else:
            top = compact[:-5] if len(compact) >= 8 else compact[:-4]
            bottom = compact[len(top):]

        top = re.sub(r'[^A-Z0-9]', '', top)
        bottom = re.sub(r'[^0-9]', '', bottom)
        return top, bottom

    def _choose_consensus_ocr_result(self, candidates, best_result):
        plausible_candidates = [
            c for c in candidates
            if self._is_plausible_plate_number(c.get('plate_number', ''))
        ]
        if len(plausible_candidates) < 2:
            return best_result

        direct_groups = {}
        for candidate in plausible_candidates:
            strategy = candidate.get('strategy', '')
            if not strategy.startswith('direct_'):
                continue
            plate_number = candidate.get('plate_number', '')
            direct_groups.setdefault(plate_number, []).append(candidate)

        for plate_number, items in direct_groups.items():
            if len(items) < 2:
                continue

            best_direct = max(items, key=lambda item: item.get('confidence', 0.0))
            if (
                best_direct.get('confidence', 0.0) >= 0.45
                and self._same_plate_except_one_tail_char(
                    plate_number,
                    best_result.get('plate_number', '')
                )
            ):
                return {
                    'method': best_direct['method'],
                    'strategy': best_direct['strategy'] + '_direct_consensus',
                    'plate_number': best_direct['plate_number'],
                    'confidence': best_direct['confidence'],
                    'raw_text': best_direct['raw_text']
                }

        _current_top, current_bottom = self._split_plate_top_bottom(best_result.get('plate_number', ''))
        current_score = self._score_plate_candidate(
            best_result.get('plate_number', ''),
            best_result.get('confidence', 0.0)
        )

        groups = {}
        for candidate in plausible_candidates:
            _top, bottom = self._split_plate_top_bottom(candidate.get('plate_number', ''))
            if len(bottom) not in {4, 5}:
                continue
            groups.setdefault(bottom, []).append(candidate)

        best_group_bottom = current_bottom
        best_group_items = groups.get(current_bottom, [])
        best_group_rank = (len(best_group_items), np.mean([item['score'] for item in best_group_items]) if best_group_items else 0.0)

        for bottom, items in groups.items():
            rank = (len(items), np.mean([item['score'] for item in items]))
            if rank > best_group_rank:
                best_group_bottom = bottom
                best_group_items = items
                best_group_rank = rank

        if (
            best_group_bottom != current_bottom
            and len(best_group_items) >= 2
            and best_group_rank[1] >= current_score - 1.2
        ):
            consensus = max(best_group_items, key=lambda item: item['score'])
            return {
                'method': consensus['method'],
                'strategy': consensus['strategy'] + '_consensus',
                'plate_number': consensus['plate_number'],
                'confidence': consensus['confidence'],
                'raw_text': consensus['raw_text']
            }

        return best_result

    def _same_plate_except_one_tail_char(self, first_plate, second_plate):
        first_top, first_bottom = self._split_plate_top_bottom(first_plate)
        second_top, second_bottom = self._split_plate_top_bottom(second_plate)
        if not first_top or first_top != second_top:
            return False
        if len(first_bottom) != len(second_bottom) or len(first_bottom) < 4:
            return False

        diff_count = sum(1 for a, b in zip(first_bottom, second_bottom) if a != b)
        return diff_count == 1
    
    def _clean_plate_text(self, text):
        """Clean and normalize Vietnamese license plate text"""
        if not text:
            return ""
        
        text = text.upper()
        text = text.replace(" ", "").replace("  ", "")
        text = text.replace("|", "1")
        text = ''.join(c for c in text if c.isalnum() or c == '-')
        return text.strip('-')

    @staticmethod
    def _to_digit_context(char):
        digit_map = {
            'O': '0', 'D': '0',
            'I': '1', 'L': '1', 'T': '1', '|': '1',
            'Z': '2',
            'A': '4',
            'S': '5',
            'G': '6',
            'B': '8',
        }
        return char if char.isdigit() else digit_map.get(char, '')

    @staticmethod
    def _to_series_context(char):
        series_map = {
            '0': 'D',
            '1': 'T',
            '2': 'Z',
            '4': 'A',
            '5': 'S',
            '6': 'G',
            '7': 'T',
            '8': 'B',
        }
        if char.isalpha():
            return char
        return series_map.get(char, char)

    def _normalize_plate_top_line(self, text):
        compact = re.sub(r'[^A-Z0-9]', '', (text or '').upper())
        if len(compact) < 3:
            return compact

        province = ''.join(self._to_digit_context(ch) for ch in compact[:2])
        series = self._to_series_context(compact[2])
        tail = compact[3:]
        if len(tail) == 1 and (tail.isalpha() or tail == '4'):
            if tail in {'4', 'A'}:
                suffix = 'A'
            else:
                suffix = self._to_digit_context(tail) or tail
        else:
            suffix = ''.join(self._to_digit_context(ch) for ch in tail)
        return f"{province}-{series}{suffix}" if suffix else f"{province}{series}"

    def _normalize_vietnamese_plate_candidate(self, plate_number):
        if not plate_number:
            return ""

        text = plate_number.upper().replace(" ", "")
        parts = [p for p in re.split(r'-+', text) if p]

        if len(parts) >= 2:
            top = self._normalize_plate_top_line(parts[0] + parts[1] if len(parts[0]) <= 2 else parts[0])
            bottom_source = ''.join(parts[2:]) if len(parts) > 2 else parts[-1]
            if len(parts) == 2 and len(parts[0]) > 2:
                top = self._normalize_plate_top_line(parts[0])
                bottom_source = parts[1]
            bottom = ''.join(self._to_digit_context(ch) for ch in re.sub(r'[^A-Z0-9]', '', bottom_source))
            return self._apply_plate_series_corrections(f"{top}-{bottom}" if bottom else top)

        compact = re.sub(r'[^A-Z0-9]', '', text)
        if len(compact) >= 7:
            top = self._normalize_plate_top_line(compact[:-5])
            bottom = ''.join(self._to_digit_context(ch) for ch in compact[-5:])
            return self._apply_plate_series_corrections(f"{top}-{bottom}")

        return self._apply_plate_series_corrections(self._normalize_plate_top_line(compact))

    def _apply_plate_series_corrections(self, plate_number):
        text = (plate_number or '').upper()
        parts = [p for p in re.split(r'-+', text) if p]
        if len(parts) < 2:
            return text

        top = re.sub(r'[^A-Z0-9]', '', ''.join(parts[:-1]))
        bottom = re.sub(r'[^0-9]', '', parts[-1])
        if len(top) != 4 or len(bottom) not in {4, 5}:
            return text

        province = top[:2]
        series = top[2]
        suffix = top[3]
        if (
            province.isdigit()
            and 50 <= int(province) <= 59
            and suffix == '8'
            and series in {'A', 'T'}
        ):
            top = province + 'X' + suffix

        formatted_top = f"{top[:2]}-{top[2:]}" if len(top) == 4 else top
        return f"{formatted_top}-{bottom}" if bottom else formatted_top

    @staticmethod
    def _is_plausible_plate_number(plate_number):
        text = (plate_number or '').upper()
        compact = re.sub(r'[^A-Z0-9]', '', text)
        if len(compact) < 7 or len(compact) > 9:
            return False
        if not compact[:2].isdigit():
            return False
        if not compact[2].isalpha():
            return False

        parts = [p for p in re.split(r'-+', text) if p]
        if len(parts) >= 3:
            top = ''.join(parts[:-1])
            bottom = parts[-1]
        elif len(parts) == 2:
            top, bottom = parts
        else:
            top = compact[:-5] if len(compact) >= 8 else compact[:-4]
            bottom = compact[len(top):]

        top = re.sub(r'[^A-Z0-9]', '', top)
        bottom = re.sub(r'[^A-Z0-9]', '', bottom)
        if len(top) not in {3, 4}:
            return False
        if len(bottom) not in {4, 5}:
            return False

        return bottom.isdigit()
    
    def recognize_multiple(self, image_folder):
        """Recognize plates from multiple images"""
        image_files = utils.get_image_files(str(image_folder))
        
        all_results = []
        
        for image_file in image_files:
            utils.log_message(f"Processing {image_file.name}...")
            result = self.recognize_plate(str(image_file))
            all_results.append(result)
        
        return all_results
    
    def visualize_results(self, image_path, output_path=None):
        """Visualize recognition results"""
        image = utils.load_image(str(image_path))
        result = self.recognize_plate(str(image_path))
        
        # Draw detected plates and results
        for plate_info in result['plates']:
            x, y, w, h = plate_info['bbox']
            plate_number = plate_info['recognition']['plate_number']
            confidence = plate_info['recognition']['confidence']
            
            # Draw bounding box
            cv2.rectangle(image, (x, y), (x + w, y + h), (0, 255, 0), 2)
            
            # Draw text
            text = f"{plate_number} ({confidence:.2f})"
            cv2.putText(image, text, (x, y - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        
        # Save or display
        if output_path:
            utils.save_image(str(output_path), image)
            utils.log_message(f"Saved result to {output_path}")
        else:
            utils.display_image("License Plate Recognition", image)
        
        return image


def main():
    """Main inference script"""
    utils.create_directories()
    
    # Example usage
    model_path = Path(config.MODELS_PATH) / 'cnn_model.h5'
    
    # Initialize recognizer
    recognizer = LicensePlateRecognizer(model_path=model_path if model_path.exists() else None)
    
    # Process sample image
    test_image = 'test_image.jpg'  # Replace with actual image path
    
    if Path(test_image).exists():
        utils.log_message(f"Processing {test_image}...")
        result = recognizer.recognize_plate(test_image)
        
        for plate_info in result['plates']:
            plate_num = plate_info['recognition']['plate_number']
            confidence = plate_info['recognition']['confidence']
            utils.log_message(f"Recognized: {plate_num} (Confidence: {confidence:.4f})")
        
        # Visualize
        recognizer.visualize_results(test_image, output_path='result.jpg')
    else:
        utils.log_message(f"Test image {test_image} not found", 'WARNING')


if __name__ == '__main__':
    main()
