# Configuration for License Plate Recognition System

# Dataset paths
DATA_RAW_PATH = 'data/raw'
DATA_PROCESSED_PATH = 'data/processed'
MODELS_PATH = 'models'
RESULTS_PATH = 'results'

# Image preprocessing parameters
IMG_WIDTH = 128
IMG_HEIGHT = 32
IMG_CHANNELS = 3

# Character recognition parameters
# Vietnamese standard: exclude I, O, Q to avoid confusion with 1, 0
ALLOWED_CHARS = '0123456789ABCDEFGHJKLMNPRSTUVWXYZ'
NUM_CLASSES = len(ALLOWED_CHARS)
MAX_PLATE_LENGTH = 12

# Vietnamese License Plate Standards
VIETNAM_OCR_ENABLED = True
VIETNAM_PLATE_FORMATS = [
    'new',   # XX - YY.ZZ format (new standard)
    'old'    # XX.AB.123 format (old standard)
]
VIETNAM_CONFIDENCE_THRESHOLD = 0.3  # EasyOCR confidence threshold for Vietnamese plates

# Model training parameters
BATCH_SIZE = 32
EPOCHS = 50
LEARNING_RATE = 0.001
VALIDATION_SPLIT = 0.2
TEST_SPLIT = 0.1

# Detection parameters (for plate detection)
CASCADE_PATH = 'models/haarcascade_licence_plate.xml'
MIN_CONTOUR_AREA = 500
MAX_CONTOUR_AREA = 500000

# Model architectures
ARCHITECTURE = {
    'plate_detector': 'yolov3',  # or 'cascade' for Haar Cascade
    'char_recognizer': 'cnn',     # Convolutional Neural Network
}

# Preprocessing settings
BLUR_KERNEL = (5, 5)
THRESHOLD_VALUE = 127
MORPH_KERNEL_SIZE = (5, 5)

# Confidence thresholds
DETECTION_CONFIDENCE = 0.5
RECOGNITION_CONFIDENCE = 0.7
