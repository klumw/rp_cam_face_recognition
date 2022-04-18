#! /usr/bin/python

# import the necessary packages
import threading
from threading import Event,Lock
from imutils.video import VideoStream
import face_recognition
import imutils
import pickle
import time
import queue
import RPi.GPIO as GPIO
import paho.mqtt.client as mqtt

# MQTT Broker, ip or server name
MQTT_BROKER = "home1"
# PIR sensor topic
TOPIC_PIR = "face/pir/01"
# Recognized name topic
TOPIC_RECOGNIZED_NAME = "face/name/01"
# Unrecognized face topic
TOPIC_UNRECOGNICED_FACE = "face/unrecognized/01"
# Setup mqtt client
mqtt_client = mqtt.Client("rp3")
# Que with captured encodings
encodingQueue = queue.Queue(2)
# Event used to exit script
exitEvent = Event()
# Set mode to BCM numbering scheme
GPIO.setmode(GPIO.BCM)
# GPIO PIR sensor input
GPIO_PIR = 6
# Setup PIR sensor input
GPIO.setup(GPIO_PIR, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Initialize 'currentname' to trigger only when a new person is identified.
currentname = "unknown"
names=[]
# Determine faces from encodings.pickle file model created from train_model.py
encodingsP = "encodings.pickle"
lock = Lock()

# publish message on topic
def mqtt_publish(topic, value):
    mqtt_client.connect(MQTT_BROKER)
    mqtt_client.publish(topic, value)

# check if pir sensor is active
def pir_active():
    if GPIO.input(GPIO_PIR) == 1:
        return True
    else:
        return False

# get encodings (only if pir sensor is active)
def get_encodings(vs):
    global names
    while True:
        if pir_active():
            frame = vs.read()
            frame = imutils.resize(frame, width=500)
            boxes = face_recognition.face_locations(frame)
            # get encodings if we have face locations
            if len(boxes) > 0:
                encodings = face_recognition.face_encodings(frame, boxes)
                encodingQueue.put(encodings)
        else:
            # if pir sensor is inactive set topic to OFF
            mqtt_publish(TOPIC_PIR, "OFF")
            lock.acquire()
            names=[]
            lock.release()
            print("PIR->OFF")
            # Wait for rising edge on pir sensor input
            while(True):
                GPIO.wait_for_edge(GPIO_PIR, GPIO.RISING, timeout=5000)
                if pir_active():
                    print("PIR->ON")
                    mqtt_publish(TOPIC_PIR, "ON")
                    break
                #exit loop if exit event is set
                if exitEvent.is_set():
                    break   
        # stop thread if exit event is set
        if exitEvent.is_set():
            break

# check encodings (only if we have data in the queue)
def check_encodings(data):
    global names
    while True:
        # if event is set end thread
        if exitEvent.is_set():
            break
        # Wait for some time if no data available
        if encodingQueue.empty():
            time.sleep(2.0)
        else:
            # read encodings if we have data
            encodings = encodingQueue.get()
            for encoding in encodings:
                # attempt to match each face in the input image to our known
                # encodings
                matches = face_recognition.compare_faces(data["encodings"],
                                                         encoding)
                name = "Unknown"  # if face is not recognized, then print Unknown

                # check to see if we have found a match
                if True in matches:
                    # find the indices of all matched faces then initialize a
                    # dictionary to count the total number of times each face
                    # was matched
                    matchedIdxs = [i for (i, b) in enumerate(matches) if b]
                    counts = {}

                    # loop over the matched indices and maintain a count for
                    # each recognized face
                    for i in matchedIdxs:
                        name = data["names"][i]
                        counts[name] = counts.get(name, 0) + 1

                    # determine the recognized face with the largest number
                    # of votes (note: in the event of an unlikely tie Python
                    # will select first entry in the dictionary)
                    name = max(counts, key=counts.get)

                    # If someone in your dataset is identified, print their name on the screen
                    lock.acquire()
                    if not(name in names):
                        print("Recognized:", name)
                        #update recognized name topic
                        mqtt_publish(TOPIC_RECOGNIZED_NAME, name)
                        names.append(name)
                    lock.release()
                else:
                    #update unrecognized face topic
                    mqtt_publish(TOPIC_UNRECOGNICED_FACE, name)
                    print('Unrecognized face')

# load the known faces and embeddings along with OpenCV's Haar
# cascade for face detection
print("Starting....")
data = pickle.loads(open(encodingsP, "rb").read())

# initialize the video stream and allow the camera sensor to warm up
# Set the ser to the followng
# src = 0 : for the build in single web cam, could be your laptop webcam
# src = 2 : I had to set it to 2 inorder to use the USB webcam attached to my laptop
#vs = VideoStream(src=2,framerate=10).start()
vs = VideoStream(usePiCamera=True).start()
time.sleep(2.0)
# Create threads
t1 = threading.Thread(target=get_encodings, args=(vs,))
t2 = threading.Thread(target=check_encodings, args=(data,))
#Start threads
t1.start()
t2.start()
#run main loop
while True:
    try:
        time.sleep(2.0)
    except KeyboardInterrupt:
        exitEvent.set()
        break
t1.join()
t2.join()
vs.stop()
GPIO.cleanup(GPIO_PIR)
