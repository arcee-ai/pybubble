FROM alpine:latest

RUN apk add --no-cache python3 bash curl wget py3-numpy py3-pandas py3-httpx py3-requests py3-pillow py3-pip imagemagick ripgrep

# Set up uv
RUN wget https://github.com/astral-sh/uv/releases/download/0.10.3/uv-x86_64-unknown-linux-musl.tar.gz
RUN tar -xzvf uv-x86_64-unknown-linux-musl.tar.gz
RUN mv uv-x86_64-unknown-linux-musl/* /usr/bin/
RUN rm -rfv uv-x86_64-unknown-linux-musl*

RUN adduser -D sandbox -u 1000
USER sandbox