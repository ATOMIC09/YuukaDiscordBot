import cv2
from utils import deepfryer_fn

def deepfry(path):
    imageNormal = cv2.imread(path)
    deepfryer_fn.printFolders("asset/deepfry/deepfryer_input", "asset/deepfry/deepfryer_output")
    deepfryer_fn.processArgs()
    deepfryer_fn.fryImage(path)
    deepfryer_fn.badPosterize(imageNormal)

    if "_deepfryer" in path:
        deepfryer_fn.folderCheck("asset/deepfry/deepfryer_input", "asset/deepfry/deepfryer_output", '.png')
    else:
        deepfryer_fn.folderCheck("asset/deepfry/deepfryer_input", "asset/deepfry/deepfryer_output", '_deepfryer.png')