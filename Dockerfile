FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY bot.py db.py utils.py messages.py constants.py admin.py ./

CMD ["python", "bot.py"]
