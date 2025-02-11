FROM gorialis/discord.py:3.10.15-bookworm-master-minimal

WORKDIR /app

COPY requirements.txt ./
RUN pip install "pip<24.1"
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "main.py"]

# Build with "docker build -t yuukabot ."
# Run with "docker run -d --restart=unless-stopped --env-file=.env yuukabot"