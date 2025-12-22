import cv2

pipeline = (
    "nvarguscamerasrc ! "
    "video/x-raw(memory:NVMM), width=1920, height=1080, framerate=30/1 ! "
    "nvvidconv ! "
    "video/x-raw, format=BGRx ! "
    "videoconvert ! "
    "video/x-raw, format=BGR ! "
    "appsink"
)

cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
print("opened:", cap.isOpened())

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break
    cv2.imshow("CSI", frame)
    if cv2.waitKey(1) == 27:
        break
