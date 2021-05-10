FROM python:3.8

WORKDIR /usr/src/fabnotion

COPY requirements.txt .

RUN pip install -r requirements.txt

ENV TZ=America/Los_Angeles
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY config.json .
COPY README.md .
COPY setup.cfg .
COPY setup.py .
COPY stockroom/* ./stockroom/

RUN python -m pip install -e .

CMD [ "python", "-m", "stockroom.stockroom" ]