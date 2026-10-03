FROM python:3.12-alpine

RUN apk add --no-cache curl bash

COPY flood.py /flood.py
RUN chmod +x /flood.py

ENTRYPOINT ["python", "/flood.py"]
CMD ["--host", "localhost", "--port", "80"]
