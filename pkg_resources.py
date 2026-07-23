import importlib.resources
import io

def resource_stream(package_or_requirement, resource_name):
    # Petpetgif passes "petpetgif.petpet" or similar, and "img/petX.gif"
    try:
        # Fallback for Python 3.9+ 
        return importlib.resources.files(package_or_requirement.split('.')[0]).joinpath(resource_name).open('rb')
    except AttributeError:
        # Older python fallback
        return importlib.resources.open_binary(package_or_requirement.split('.')[0], resource_name)
