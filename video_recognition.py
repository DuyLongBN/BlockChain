"""
Real-time license plate recognition from video or camera
"""
import cv2
import numpy as np
import tempfile
import os
from pathlib import Path
from inference import LicensePlateRecognizer
import config
from src import utils


class VideoPlateRecognizer:
    """Real-time license plate recognition from video"""
    
    def __init__(self, model_path=None):
        self.recognizer = LicensePlateRecognizer(model_path=model_path)
        # Create temp directory for frame processing
        self._temp_dir = tempfile.mkdtemp()
    
    def _recognize_frame(self, frame):
        """
        Recognize plates from a video frame (numpy array)
        Args:
            frame: BGR numpy array
        Returns:
            List of plate detection results
        """
        # Save frame to temp file for recognize_plate()
        temp_path = os.path.join(self._temp_dir, '_frame.jpg')
        cv2.imwrite(temp_path, frame)
        
        result = self.recognizer.recognize_plate(temp_path)
        
        # Flatten the nested result structure into a simple list
        detections = []
        for plate_info in result.get('plates', []):
            recognition = plate_info.get('recognition', {})
            detections.append({
                'bbox': plate_info.get('bbox', (0, 0, 0, 0)),
                'plate_number': recognition.get('plate_number', 'UNKNOWN'),
                'confidence': recognition.get('confidence', 0.0)
            })
        
        return detections

    @staticmethod
    def _bbox_to_xyxy(bbox):
        """Convert recognizer bbox format (x, y, w, h) to draw coordinates."""
        if not bbox or len(bbox) != 4:
            return None

        x, y, w, h = [int(v) for v in bbox]
        if w <= 0 or h <= 0:
            return None

        return x, y, x + w, y + h
    
    def process_video(self, video_path, output_path=None, confidence_threshold=0.5, render_preview=True):
        """
        Process video file
        Args:
            video_path: Path to input video
            output_path: Path to save output video
            confidence_threshold: Minimum confidence for displaying results
            render_preview: Show OpenCV preview window. Disable this in web/server mode.
        """
        cap = cv2.VideoCapture(str(video_path))
        
        if not cap.isOpened():
            utils.log_message(f"Cannot open video: {video_path}", 'ERROR')
            return []
        
        # Get video properties
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not fps or fps <= 0:
            fps = 25
        
        utils.log_message(f"Video: {width}x{height} @ {fps:.1f}fps, {total_frames} frames")
        
        # Video writer
        if output_path:
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))
        else:
            out = None
        
        frame_count = 0
        plate_detections = []
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            frame_count += 1
            
            # Recognize plates
            results = self._recognize_frame(frame)
            
            # Draw results
            for result in results:
                if result['confidence'] >= confidence_threshold:
                    bbox = result['bbox']
                    plate_number = result['plate_number']
                    confidence = result['confidence']
                    
                    # Handle both bbox formats: (x1,y1,x2,y2) and (x,y,w,h)
                    xyxy = self._bbox_to_xyxy(bbox)
                    if not xyxy:
                        continue
                    x, y, x2, y2 = xyxy
                    
                    # Draw box (green)
                    cv2.rectangle(frame, (x, y), (x2, y2), (0, 255, 0), 2)
                    
                    # Draw text with background
                    text = f"{plate_number} ({confidence:.2f})"
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    font_scale = 0.6
                    thickness = 2
                    
                    text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
                    text_x = max(x, 5)
                    text_y = max(y - 5, 20)
                    
                    # Background rectangle for text
                    cv2.rectangle(frame, 
                                 (text_x - 3, text_y - text_size[1] - 3),
                                 (text_x + text_size[0] + 3, text_y + 3),
                                 (0, 255, 0), -1)
                    
                    # Draw text (black)
                    cv2.putText(frame, text, (text_x, text_y),
                               font, font_scale, (0, 0, 0), thickness)
                    
                    plate_detections.append({
                        'frame': frame_count,
                        'plate': plate_number,
                        'confidence': confidence
                    })
            
            # Display frame info
            info_text = f"Frame: {frame_count}/{total_frames}"
            cv2.putText(frame, info_text, (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            # Write frame
            if out:
                out.write(frame)
            
            if render_preview:
                cv2.imshow('License Plate Recognition', frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            
            if frame_count % 30 == 0:
                utils.log_message(f"Processed {frame_count}/{total_frames} frames")
        
        # Release resources
        cap.release()
        if out:
            out.release()
        if render_preview:
            cv2.destroyAllWindows()
        
        # Print summary
        print(f"\nProcessing completed!")
        print(f"Total frames: {frame_count}")
        print(f"Plates detected: {len(plate_detections)}")
        
        if output_path:
            utils.log_message(f"Output video saved to {output_path}")
        
        return plate_detections
    
    def process_camera(self, confidence_threshold=0.5, max_duration=60):
        """
        Process video from camera
        Args:
            confidence_threshold: Minimum confidence for displaying
            max_duration: Maximum duration in seconds
        """
        cap = cv2.VideoCapture(0)
        
        if not cap.isOpened():
            utils.log_message("Cannot open camera", 'ERROR')
            return
        
        utils.log_message("Camera opened. Press 'q' to quit")
        
        import time
        start_time = time.time()
        frame_count = 0
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            frame_count += 1
            
            # Recognize plates
            results = self._recognize_frame(frame)
            
            # Draw results
            for result in results:
                if result['confidence'] >= confidence_threshold:
                    bbox = result['bbox']
                    plate_number = result['plate_number']
                    confidence = result['confidence']
                    
                    # Handle both bbox formats: (x1,y1,x2,y2) and (x,y,w,h)
                    xyxy = self._bbox_to_xyxy(bbox)
                    if not xyxy:
                        continue
                    x, y, x2, y2 = xyxy
                    
                    # Draw box (green)
                    cv2.rectangle(frame, (x, y), (x2, y2), (0, 255, 0), 2)
                    
                    # Draw text with background
                    text = f"{plate_number} ({confidence:.2f})"
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    font_scale = 0.6
                    thickness = 2
                    
                    text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
                    text_x = max(x, 5)
                    text_y = max(y - 5, 20)
                    
                    # Background rectangle for text
                    cv2.rectangle(frame, 
                                 (text_x - 3, text_y - text_size[1] - 3),
                                 (text_x + text_size[0] + 3, text_y + 3),
                                 (0, 255, 0), -1)
                    
                    # Draw text (black)
                    cv2.putText(frame, text, (text_x, text_y),
                               font, font_scale, (0, 0, 0), thickness)
            
            # Display
            cv2.imshow('License Plate Recognition', frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
            
            # Check duration
            if time.time() - start_time > max_duration:
                break
        
        cap.release()
        cv2.destroyAllWindows()
        
        utils.log_message(f"Processed {frame_count} frames from camera")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Real-time license plate recognition')
    parser.add_argument('--video', type=str, help='Input video file path')
    parser.add_argument('--camera', action='store_true', help='Use camera as input')
    parser.add_argument('--output', type=str, help='Output video file path')
    parser.add_argument('--model', type=str, help='Path to trained model')
    parser.add_argument('--confidence', type=float, default=0.5, help='Confidence threshold')
    
    args = parser.parse_args()
    
    recognizer = VideoPlateRecognizer(model_path=args.model)
    
    if args.video:
        recognizer.process_video(args.video, args.output, args.confidence)
    elif args.camera:
        recognizer.process_camera(args.confidence)
    else:
        print("Please provide --video or --camera option")
