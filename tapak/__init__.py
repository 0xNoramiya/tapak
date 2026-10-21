"""TAPAK: leak attribution for classified documents."""

import os

# OpenCV refuses to decode images above this many pixels, for every format it reads (WebP,
# TIFF and BMP included), after reading only the header: a small file cannot make the decoder
# allocate gigabytes. It must be set before cv2 is imported, hence here.
os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", "60000000")
