FROM python:3

WORKDIR /

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY templates /templates
COPY parser.py /parser.py
COPY start.sh /start.sh

CMD [ "bash", "./start.sh" ]