FROM python:3-alpine

WORKDIR /app

COPY ./requirements.txt /app/requirements.txt 

RUN pip install --no-cache-dir -r /app/requirements.txt

COPY ./src /app

CMD ["fastapi", "run", "/app/main.py", "--port", "8000", "--host", "0.0.0.0"]