#!/usr/bin/python

# Start up ROS pieces.
import roslib
import rosbag
import rospy
import cv2
from sensor_msgs.msg import Image
from cv_bridge import CvBridge, CvBridgeError

# Reading bag filename from command line or roslaunch parameter.
import os
import sys

class ImageCreator():
    # Must have __init__(self) function for a class, similar to a C++ class constructor.
    def __init__(self, save_dir, filename):
            
        # Use a CvBridge to convert ROS images to OpenCV images so they can be saved.
        self.bridge = CvBridge()
            
        # Open bag file.
        with rosbag.Bag(filename, 'r') as bag:
            for topic, msg, t in bag.read_messages():
                if topic == "/SR300/rgb/image_raw":
                    try:
                        cv_image = self.bridge.imgmsg_to_cv2(msg, "bgr8")
                    except CvBridgeError, e:
                        print e
                    timestr = "%.6f" % msg.header.stamp.to_sec()
                    image_name = str(save_dir)+"/image_"+timestr+".jpg"
                    cv2.imwrite(image_name, cv_image)


def export_jpgs(data_path, subject_name):

    # get rosbags path
    subject_path = os.path.join(data_path,subject_name)
    bag_files = os.listdir(subject_path)

    # For loop
    for idx, f in enumerate(bag_files):
        print idx, "/" len(bag_files), " : ", f

        folder_name = f.split(f)[1].split('.')[0]

        # create save folder
        save_dir = os.path.join(subject_path, folder_name)
        if not os.path.isdir(save_dir):
            os.makedirs(save_dir)

        # export
        image_creator = ImageCreator(save_dir, f)



    
# Main function.
if __name__ == '__main__':
    # Initialize the node and name it.
    rospy.init_node("export_jpgs")
    # Go to class functions that do all the heavy lifting. Do error checking.
    ## try:
    ##     image_creator = ImageCreator()
    ## except rospy.ROSInterruptException: pass

    export_jpgs(sys.path[0], sys.argv[1])
        
