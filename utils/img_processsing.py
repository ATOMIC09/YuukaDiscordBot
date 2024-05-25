import cv2
from utils import deepfryer
import requests
import os
import math
from urllib.parse import urlparse, parse_qs

def deepfry(path):
    imageNormal = cv2.imread(path)
    deepfryer.printFolders("temp/deepfry/deepfryer_input", "temp/deepfry/deepfryer_output")
    deepfryer.processArgs()
    deepfryer.fryImage(path)
    deepfryer.badPosterize(imageNormal)

    if "_deepfryer" in path:
        deepfryer.folderCheck("temp/deepfry/deepfryer_input", "temp/deepfry/deepfryer_output", '.png')
    else:
        deepfryer.folderCheck("temp/deepfry/deepfryer_input", "temp/deepfry/deepfryer_output", '_deepfried.png')

def wide(path,stretch):
    image = cv2.imread(path,cv2.IMREAD_UNCHANGED)
    try:
        b_channel, g_channel, r_channel , alpha = cv2.split(image)
        img_RGBA = cv2.merge((b_channel, g_channel, r_channel, alpha))
    except:
        b_channel, g_channel, r_channel = cv2.split(image)
        img_RGBA = cv2.merge((b_channel, g_channel, r_channel))

    height, width, channels = img_RGBA.shape
    size = (math.ceil(width*2), math.ceil(height/stretch))

    res = cv2.resize(img_RGBA, size)
    cv2.imwrite(path,res)

def scale(path,scale):
    image = cv2.imread(path)
    height, width, channels = image.shape
    size = (math.ceil(width*scale), math.ceil(height*scale))
    try:
        res = cv2.resize(image, size)
    except:
        return "ไม่สามารถปรับขนาดภาพได้"
    cv2.imwrite(path,res)

def resize(path,width,height):
    img = cv2.imread(path)
    try:
        resized = cv2.resize(img, (width, height))
    except:
        return "ไม่สามารถปรับขนาดภาพได้"
    cv2.imwrite(path,resized)

def grayscale(path):
    img = cv2.imread(path,cv2.IMREAD_UNCHANGED)

    # Save the transparency channel alpha
    *_, alpha = cv2.split(img)

    gray_layer = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    img = cv2.merge((gray_layer, gray_layer, gray_layer, alpha))
    
    cv2.imwrite(path,img)

# File management
def save_image_from_url(url, filename):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            with open(filename, 'wb') as file:
                file.write(response.content)
                print(f"Image saved as {filename}")
        else:
            print("Failed to fetch the image")
    except Exception as e:
        print(f"An error occurred: {e}")

def get_filename(url):
    parsed_url = urlparse(url)
    file_name = os.path.basename(parsed_url.path)
    file_name_only, ext = os.path.splitext(file_name)
    return file_name, file_name_only, ext

def get_shape(path):
    image = cv2.imread(path,cv2.IMREAD_UNCHANGED)

    height, width, channels = image.shape
    return width, height, channels