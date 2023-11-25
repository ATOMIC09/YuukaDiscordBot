# -*- coding: utf-8 -*-
"""
Created on Thu Nov 16 08:35:10 2017

@author: Pablo Nunes
"""

import cv2
import numpy as np
import sys
from os import path, listdir


def argInstructions():
    """ Shows what the script uses, what args it uses and what it does. """
    """ Only put images in the input folder, everything in the input folder will tried to be converted in images on the output folder.  """
    print ("Needs: Python 3, numpy and OpenCV")
    print ("Usage: <inputFolder> <outputFolder='output/'>")
    print ("Does: Deep Fries the images in a folder and output them at the output folder")


def printFolders(inputFolder, outputFolder):
    """
    Shows the input folder and the output folder
    :param inputFolder: string | inputFolder | Input folder path
    :param outputFolder: string | outputFolder | Output folder path
    """
    print ("Showing the input and output folders: ")
    print ("Input folder:\t" + inputFolder)
    print ("Output folder:\t" + outputFolder)


def processArgs():
    """
    Process the args for use in the script
    """

    inputFolder = "deepfryer_input"
    outputFolder = "deepfryer_output"
    if len(sys.argv) >= 3:
        pass
    else:
        'Output'
    return inputFolder, outputFolder


def fryImage(imagePath):
    """
    Passes the image path, opens it with OpenCV and returns the image with drastic posterization
    :param imagePath: string | imagePath | Full image path
    """
    imageStart = cv2.imread(imagePath)
    return badPosterize(imageStart)


def badPosterize(imageNormal):
    """
    Posterize the image through a color list, diving it and making a pallete.
    Finally, applying to the image and returning the image with a the new pallete
    :param imageNormal: CV opened image | imageNormal | The normal image opened with OpenCV
    """
    colorList = np.arange(0, 256)
    colorDivider = np.linspace(0, 255,3)[1]
    colorQuantization = np.int0(np.linspace(0, 255, 2))
    colorLevels = np.clip(np.int0(colorList/colorDivider), 0, 1)
    colorPalette = colorQuantization[colorLevels]
    return colorPalette[imageNormal]


def folderCheck(inputFolder, outputFolder, extension): # นับจำนวน
    """
    It receives the folder, get all files and make a pair for each open file
    After that, each pair is posterized and is saved at lower quality.
    With the image being fryed and being saved at the output folder plus a "-fry" for the fried one.
    :param inputFolder: string | inputFolder | Input folder path
    :param outputFolder: string | outputFolder | Output folder path
    """
    namePairs = [path.splitext(nameWithFormat) for nameWithFormat in listdir(inputFolder)]

    for (fileName, formatName) in namePairs:
        imageOpen = cv2.imread(path.join(inputFolder, fileName + formatName))
        imageFry = badPosterize(imageOpen)
        cv2.imwrite(path.join(outputFolder, fileName + extension), imageFry, [int(cv2.IMWRITE_JPEG_QUALITY), 0])

    return len(namePairs)


if __name__ == "__main__":

    if len(sys.argv) == 3:
        inputFolder, outputFolder = processArgs()
        printFolders(inputFolder, outputFolder)
        print ("Fried Images:\t", folderCheck(inputFolder,outputFolder))
    else:
        argInstructions()
