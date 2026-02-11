FROM python:3.9.19

COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

#ARG USERNAME=vscode
#ARG USER_UID=1000
#ARG USER_GID=44
#
#RUN groupadd --gid $USER_GID $USERNAME \
#    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME

COPY . /workspace
WORKDIR /workspace

#USER $USERNAME

# 例えば streamer.py 実行デフォルトにしたいなら
CMD ["python", "main.py"]