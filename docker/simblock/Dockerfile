# Execution image for SimBlock.
#
# SimBlock is compiled with plain javac inside each simulation run, so the
# image needs only a JDK and the pinned SimBlock source. The upstream Gradle
# wrapper (6.7.1) is not used because it does not run on current JDKs.
#
# Build with `uv run abc-harness image build`.

# eclipse-temurin:21-jdk, pinned by digest.
FROM eclipse-temurin@sha256:db5cc6341a1d7bc40cdb51e1f0d9824f3bb2cc8107d29da421dc4df7d11f05f1

ARG SIMBLOCK_COMMIT=8a1285aa37b832385b0be2ae6f804885a4a7031f

ADD --checksum=sha256:b9e858fb0f44755d23aa64cc24d1c17d2a93bb3cac3261bccaaa58984f2f2462 \
    https://github.com/dsg-titech/simblock/archive/${SIMBLOCK_COMMIT}.tar.gz /tmp/simblock.tar.gz

RUN mkdir -p /opt/simblock \
 && tar -xzf /tmp/simblock.tar.gz -C /opt/simblock --strip-components=1 \
 && rm /tmp/simblock.tar.gz \
 && echo "${SIMBLOCK_COMMIT}" > /opt/simblock/REVISION

LABEL org.abc-harness.simulator="simblock" \
      org.abc-harness.simblock-commit="${SIMBLOCK_COMMIT}"

WORKDIR /work
