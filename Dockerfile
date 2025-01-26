FROM gorialis/discord.py:3.10.15-bookworm-master-minimal

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "main.py"]
