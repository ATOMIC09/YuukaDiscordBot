import io
from PIL import Image, ImageEnhance, ImageOps, ExifTags, ImageSequence
from petpetgif import petpet
import qrcode
import logging
import aiohttp

logger = logging.getLogger(__name__)

def _process_image(img_bytes: bytes, frame_processor: callable, force_jpeg: bool = False) -> tuple[io.BytesIO, str, tuple[int, int], tuple[int, int]]:
    img = Image.open(io.BytesIO(img_bytes))
    original_size = img.size
    
    if getattr(img, "is_animated", False):
        frames = []
        for frame in ImageSequence.Iterator(img):
            frame = frame.copy()
            processed_frame = frame_processor(frame)
            frames.append(processed_frame)
            
        output = io.BytesIO()
        frames[0].save(
            output,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            loop=img.info.get('loop', 0),
            duration=img.info.get('duration', 100),
            disposal=2
        )
        output.seek(0)
        return output, "gif", original_size, frames[0].size
    else:
        processed_frame = frame_processor(img)
        output = io.BytesIO()
        if force_jpeg:
            processed_frame.save(output, format="JPEG", quality=0)
            ext = "jpg"
        else:
            processed_frame.save(output, format="PNG")
            ext = "png"
        output.seek(0)
        return output, ext, original_size, processed_frame.size

def make_deepfry(img_bytes: bytes) -> tuple[io.BytesIO, str, tuple[int, int], tuple[int, int]]:
    def process_frame(frame):
        frame = frame.convert("RGB")
        frame = frame.point(lambda p: 255 if p > 127 else 0)
        
        # Deepfry needs JPEG artifacts. To keep this effect for GIFs, save each frame to a temp JPEG in memory.
        temp_io = io.BytesIO()
        frame.save(temp_io, format="JPEG", quality=0)
        temp_io.seek(0)
        return Image.open(temp_io)
        
    return _process_image(img_bytes, process_frame, force_jpeg=True)

def make_grayscale(img_bytes: bytes) -> tuple[io.BytesIO, str, tuple[int, int], tuple[int, int]]:
    def process_frame(frame):
        frame = frame.convert("RGBA")
        alpha = frame.getchannel('A')
        frame = ImageOps.grayscale(frame).convert("RGBA")
        frame.putalpha(alpha)
        return frame
        
    return _process_image(img_bytes, process_frame)

def make_wide(img_bytes: bytes) -> tuple[io.BytesIO, str, tuple[int, int], tuple[int, int]]:
    def process_frame(frame):
        width, height = frame.size
        new_size = (width * 2, max(1, height // 2))
        return frame.resize(new_size, Image.Resampling.LANCZOS)
        
    return _process_image(img_bytes, process_frame)

def make_resize(img_bytes: bytes, w: int, h: int) -> tuple[io.BytesIO, str, tuple[int, int], tuple[int, int]]:
    def process_frame(frame):
        return frame.resize((w, h), Image.Resampling.LANCZOS)
        
    return _process_image(img_bytes, process_frame)

def make_scale(img_bytes: bytes, scale: float) -> tuple[io.BytesIO, str, tuple[int, int], tuple[int, int]]:
    def process_frame(frame):
        width, height = frame.size
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        return frame.resize(new_size, Image.Resampling.LANCZOS)
        
    return _process_image(img_bytes, process_frame)

def make_qr(text: str, logo_bytes: bytes | None = None) -> tuple[io.BytesIO, str, tuple[int, int], tuple[int, int]]:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(text)
    qr.make(fit=True)
    
    if logo_bytes is None:
        img = qr.make_image(fill_color="black", back_color="white")
    else:
        logo = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")
        
        basewidth = int(qr_img.size[0] * 0.25)
        wpercent = (basewidth / float(logo.size[0]))
        hsize = int((float(logo.size[1]) * float(wpercent)))
        logo = logo.resize((basewidth, hsize), Image.Resampling.LANCZOS)
        
        pos = ((qr_img.size[0] - logo.size[0]) // 2, (qr_img.size[1] - logo.size[1]) // 2)
        
        white_bg = Image.new("RGBA", logo.size, "white")
        white_bg.paste(logo, (0, 0), logo)
        
        qr_img.paste(white_bg, pos)
        img = qr_img
        
    output = io.BytesIO()
    img.save(output, format="PNG")
    output.seek(0)
    return output, "png", img.size, img.size

def make_petpet(img_bytes: bytes) -> tuple[io.BytesIO, str, tuple[int, int], tuple[int, int]]:
    img = Image.open(io.BytesIO(img_bytes))
    original_size = img.size
    
    input_io = io.BytesIO(img_bytes)
    output_io = io.BytesIO()
    petpet.make(input_io, output_io)
    output_io.seek(0)
    return output_io, "gif", original_size, (112, 112)

def get_image_info(img_bytes: bytes) -> dict:
    img = Image.open(io.BytesIO(img_bytes))
    
    channels = len(img.getbands())
    if channels == 1:
        channel_type = "Grayscale"
    elif channels == 2:
        channel_type = "Grayscale Alpha"
    elif channels == 3:
        channel_type = "RGB"
    elif channels == 4:
        channel_type = "RGBA"
    else:
        channel_type = "Unknown"
        
    width, height = img.size
    
    info = {
        "channel_type": channel_type,
        "width": width,
        "height": height,
        "date_taken": "N/A",
        "camera_make": "N/A",
        "camera_model": "N/A",
        "exposure_time": "N/A",
        "f_number": "N/A",
        "iso_speed": "N/A",
        "focal_length": "N/A",
    }
    
    try:
        exif_data = img._getexif()
        if exif_data:
            exif_info = {}
            for tag, value in exif_data.items():
                tag_name = ExifTags.TAGS.get(tag, tag)
                exif_info[tag_name] = value
                
            info["date_taken"] = exif_info.get('DateTimeOriginal', 'N/A')
            info["camera_make"] = exif_info.get('Make', 'N/A')
            info["camera_model"] = exif_info.get('Model', 'N/A')
            info["exposure_time"] = exif_info.get('ExposureTime', 'N/A')
            info["f_number"] = exif_info.get('FNumber', 'N/A')
            info["iso_speed"] = exif_info.get('ISOSpeedRatings', 'N/A')
            info["focal_length"] = exif_info.get('FocalLength', 'N/A')
    except Exception:
        pass
        
    return info

async def fetch_recent_image(channel, limit=20) -> bytes | None:
    async for message in channel.history(limit=limit):
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith("image/"):
                return await attachment.read()
    return None

async def download_image(url: str) -> bytes | None:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.read()
    return None
