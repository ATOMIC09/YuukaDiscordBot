import cv2
from utils import deepfryer
import requests
import os

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
    file_name = os.path.basename(url)
    file_name_only = os.path.splitext(file_name)[0]
    return file_name, file_name_only