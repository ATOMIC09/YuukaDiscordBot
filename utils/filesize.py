import os

def getsize(path):
    byte = os.path.getsize(path) 
    if byte < 1024:
        return str(byte) + ' B'
    elif byte < 1024**2:
        return str(round(byte/1024, 2)) + ' KB'
    elif byte < 1024**3:
        return str(round(byte/1024**2, 2)) + ' MB'
    elif byte < 1024**4:
        return str(round(byte/1024**3, 2)) + ' GB'
    else:
        return str(round(byte/1024**4, 2)) + ' TB'