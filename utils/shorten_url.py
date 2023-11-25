import pyshorteners

def shortenmylink(long_url):
    type_tiny = pyshorteners.Shortener()
    short_url = type_tiny.tinyurl.short(long_url)   
    return short_url