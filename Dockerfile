FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./

# Install PyTorch CPU-only versions first (using PyTorch index)
RUN pip install --no-cache-dir "pip<24.1" && \
    pip install --no-cache-dir torch==2.1.1+cpu torchaudio==2.1.1+cpu -f https://download.pytorch.org/whl/torch_stable.html && \
    pip install --no-cache-dir -r requirements.txt && \
    pip cache purge

# Copy application code
COPY . .

# Create temp directories
RUN mkdir -p temp/ai temp/audio temp/chat temp/deepfry/deepfryer_input temp/deepfry/deepfryer_output temp/image temp/sheets temp/video

CMD ["python", "main.py"]

# Build with "docker build -t yuukabot ."
# Run with "docker run -d --restart=unless-stopped --env-file=.env yuukabot"