import os
import math

def prefix(byte):
    if byte < 1024:
        return str(byte) + ' B'
    else:
        exp = min(int(math.log(byte, 1024)), 4)
        size = byte / (1024 ** exp)
        size_str = "{:.2f}".format(size)
        units = ['KB', 'MB', 'GB', 'TB']
        return size_str + ' ' + units[exp - 1]

def getsize(path):
    byte = os.path.getsize(path)
    return prefix(byte)

def getfoldersize(folder):
    total_size = 0
    for path, dirs, files in os.walk(folder):
        for f in files:
            fp = os.path.join(path, f)
            total_size += os.path.getsize(fp)

    return prefix(total_size)