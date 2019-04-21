FROM debian:stretch

ENV DEBIAN_FRONTEND noninteractive

RUN \
	sed -i 's/main$/main contrib non-free/' /etc/apt/sources.list && \
	apt-get -y update && \
	apt-get -y install apt-utils sudo && \
	apt-get -y dist-upgrade && \
	apt-get -y clean

RUN \
	apt-get -y install vim openjdk-8-jdk-headless python3 python3-venv && \
	apt-get -y clean

RUN python3 -m venv /opt/handin && /opt/handin/bin/pip3 install chardet

RUN useradd -ms /bin/bash handin
RUN echo "handin:handin" | chpasswd
RUN adduser handin sudo

USER handin
WORKDIR /home/handin
