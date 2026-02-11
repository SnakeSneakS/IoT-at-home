# ========= Build Stage =========
FROM rust:1.75-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y \
    pkg-config \
    libudev-dev \
    && rm -rf /var/lib/apt/lists/*

COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo "fn main(){}" > src/main.rs
RUN cargo build --release
RUN rm -rf src

COPY src ./src
RUN cargo build --release

# ========= Runtime Stage =========
FROM debian:bookworm-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libudev1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/target/release/arduino_serial_api .

ENV SERVER_ADDR=0.0.0.0:3000
ENV LOG_DIR=/var/log/arduino

RUN mkdir -p /var/log/arduino

EXPOSE 3000

CMD ["./arduino_serial_api"]
