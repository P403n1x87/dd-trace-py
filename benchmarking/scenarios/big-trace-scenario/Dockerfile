FROM pyddmatrix:latest
COPY ./script.py /scripts/script.py
COPY ./scenario.json /scenarios/scenario.json
ENV  DD_DOGSTATSD_PORT=8124
CMD  . /venvs/${VENV}/bin/activate ; python -V ; pip freeze ; sirun /scenarios/scenario.json > /results/${VENV}
