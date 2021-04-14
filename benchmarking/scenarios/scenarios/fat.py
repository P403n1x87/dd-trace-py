FAT_DOCKERFILE = """
FROM ubuntu:latest
COPY bin/* /usr/bin/
RUN  chmod +x /usr/bin/sirun && chmod +x /usr/bin/austin
ARG  DEBIAN_FRONTEND=noninteractive
ENV  LANG=C.UTF-8
ENV  PYENV_ROOT="/root/.pyenv"
ENV  PATH="${{PYENV_ROOT}}/shims:${{PYENV_ROOT}}/bin:${{PATH}}"
RUN  apt-get update && \
     apt-get install -y --no-install-recommends ca-certificates make build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm libncurses5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev git
RUN  curl https://pyenv.run | bash
RUN  echo $PATH
RUN  for py in {py_versions}; do \
       FULL_VERSION=`pyenv install --list | grep "^[ ]*${{py}}" | tail -n 1`; \
       pyenv install $FULL_VERSION; \
       pyenv global $FULL_VERSION; \
       pip install --upgrade pip; \
       for dd in {ddtrace_versions}; do \
         pip install venv || pip install virtualenv; \
         python -m venv /venvs/$py-$dd || python -m virtualenv /venvs/$py-$dd; \
         . /venvs/$py-$dd/bin/activate; \
         install --upgrade pip; \
         pip install ddtrace==$dd; \
       done; \
     done
"""
