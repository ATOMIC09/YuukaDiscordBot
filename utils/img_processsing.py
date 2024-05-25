import cv2
from utils import deepfryer
import requests
import os
import math
from urllib.parse import urlparse, parse_qs
import cv2
from PIL import Image
from PIL.ExifTags import TAGS
from datetime import datetime

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

def imginfo(path):
    image = cv2.imread(path, cv2.IMREAD_UNCHANGED)

    # Get the image dimensions
    height, width, channels = image.shape

    # Determine the channel type
    if channels == 1:
        channel_type = "Grayscale"
    elif channels == 2:
        channel_type = "Grayscale Alpha"
    elif channels == 3:
        channel_type = "RGB"
    elif channels == 4:
        channel_type = "RGBA"
    
    # Get the last modified time
    last_modified_time = datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M:%S')

    # Extract EXIF data
    pil_image = Image.open(path)
    exif_data = pil_image._getexif()
    exif_info = {}
    if exif_data:
        for tag, value in exif_data.items():
            tag_name = TAGS.get(tag, tag)
            exif_info[tag_name] = value

    # Extract specific EXIF information if available
    date_taken = exif_info.get('DateTimeOriginal', 'N/A')
    camera_make = exif_info.get('Make', 'N/A')
    camera_model = exif_info.get('Model', 'N/A')
    exposure_time = exif_info.get('ExposureTime', 'N/A')
    f_number = exif_info.get('FNumber', 'N/A')
    iso_speed = exif_info.get('ISOSpeedRatings', 'N/A')
    focal_length = exif_info.get('FocalLength', 'N/A')

    return {
        "channel_type": channel_type,
        "height": height,
        "width": width,
        "last_modified": last_modified_time,
        "date_taken": date_taken,
        "camera_make": camera_make,
        "camera_model": camera_model,
        "exposure_time": exposure_time,
        "f_number": f_number,
        "iso_speed": iso_speed,
        "focal_length": focal_length
    }

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