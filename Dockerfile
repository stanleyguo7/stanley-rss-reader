FROM quay.io/centos/centos:stream9

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN dnf -y install python3.11 python3.11-pip && dnf clean all

COPY requirements.txt /app/requirements.txt
RUN python3.11 -m pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

EXPOSE 8090

CMD ["python3.11", "-m", "uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8090"]
