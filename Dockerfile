FROM mcr.microsoft.com/dotnet/sdk:10.0 AS calculator
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
RUN git init /calcpad && git -C /calcpad fetch --depth=1 https://github.com/imartincei/CalcpadCE.git 0b20dba11ebd50b303eedb57e8ec042c272c68ab && git -C /calcpad checkout --detach FETCH_HEAD
COPY src/mcdxkit/calcpad_bridge /bridge
ARG TARGETARCH
RUN if [ "$TARGETARCH" = "arm64" ]; then engine_arch=arm64; else engine_arch=x64; fi; dotnet publish /bridge/Bridge.csproj -c Release -r linux-$engine_arch --self-contained true -o /calculator -p:CalcpadSource=/calcpad -p:UseSharedCompilation=false && cp /calcpad/LICENSE /calculator/CalcpadCE-LICENSE && cp /calcpad/THIRD-PARTY-NOTICES.txt /calculator/CalcpadCE-THIRD-PARTY-NOTICES.txt

FROM python:3.12-slim-bookworm AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.lock ./
RUN pip install -r requirements.lock
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-deps .

FROM python:3.12-slim-bookworm AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    MCDXKIT_HOST=0.0.0.0 MCDXKIT_OUTPUT_DIR=/data/outputs PORT=8765 MCDXKIT_ENGINE_DIR=/opt/calculator
RUN apt-get update && apt-get install -y --no-install-recommends libicu72 && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 10001 mcdxkit && useradd --uid 10001 --gid mcdxkit --no-create-home mcdxkit \
    && mkdir -p /data/outputs && chown -R mcdxkit:mcdxkit /data
COPY --from=build /opt/venv /opt/venv
COPY --from=calculator /calculator /opt/calculator
USER 10001:10001
WORKDIR /data
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8765')+'/healthz',timeout=2)"
ENTRYPOINT ["mcdxkit"]
CMD ["serve", "--no-open"]
