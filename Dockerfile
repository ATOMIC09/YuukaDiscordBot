FROM gorialis/discord.py

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY .env .
COPY . .

CMD ["python", "main.py"]
